"""
Loan Action Agent — Foundry new-agent API.

Uses AIProjectClient.agents.create_version() for registration and the
Responses API for tool-calling. Tool calls are intercepted in the response
output loop, executed locally, and results fed back via previous_response_id
— giving full visibility into inputs and outputs in the SSE event stream.

# ---------------------------------------------------------------------------
# NOTE — Future MCP migration path
# ---------------------------------------------------------------------------
# The tools are currently wired as FunctionTool (JSON schema definitions).
# As this solution matures, consider migrating to one of:
#
#   Option A — Local MCP server:
#     Wrap refi_calculator and appointment_scheduler as a local MCP server
#     using the `mcp` Python package, then connect the agent via McpTool
#     with StreamableHTTPServerParams pointing to the local server.
#
#   Option B — Hosted MCP (production):
#     Register the tools in the Azure-hosted MCP service at
#     mcp.ai.azure.com and connect via McpTool using the MCP_ENDPOINT
#     environment variable. This surfaces the tools as managed MCP
#     resources visible in the Foundry portal.
#
# Both options preserve the same SSE event schema — only the agent
# connection mechanism changes.
# ---------------------------------------------------------------------------
"""

import asyncio
import json
import logging
import os
from dataclasses import asdict
from typing import AsyncGenerator

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, FunctionTool
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential

from tools.refi_calculator import (
    RefiCalculatorInput,
    RefiCalculatorResult,
    calculate_refi_savings,
)
from tools.appointment_scheduler import (
    AppointmentInput,
    AppointmentResult,
    schedule_appointment,
)

logger = logging.getLogger(__name__)

# URL-safe agent name (alphanumeric + hyphens, max 63 chars).
_AGENT_NAME = "va-loan-action-agent"

ACTION_INSTRUCTIONS = (
    "You are a VA loan action assistant. You help Veterans understand the financial "
    "impact of refinancing and book consultations with loan officers.\n\n"
    "When asked to calculate refinance savings, call refi_savings_calculator with the "
    "loan parameters provided. When asked to schedule a consultation, call "
    "appointment_scheduler with the Veteran's preferred day and time.\n\n"
    "After receiving tool results, present the information clearly and helpfully. "
    "Lead with the monthly savings figure, highlight the break-even timeline, state "
    "whether the IRRRL passes the VA net tangible benefit test, and confirm the "
    "appointment details including the confirmation number."
)

# ---------------------------------------------------------------------------
# Tool JSON schemas — passed to PromptAgentDefinition via FunctionTool.
# ---------------------------------------------------------------------------

_REFI_TOOL_DEF = {
    "name": "refi_savings_calculator",
    "description": (
        "Calculate VA IRRRL refinance savings. Returns monthly savings, annual savings, "
        "lifetime savings, break-even timeline, closing costs, and whether the VA net "
        "tangible benefit test passes (break-even must be 36 months or fewer)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "current_rate": {
                "type": "number",
                "description": "Annual interest rate on the existing loan (e.g. 6.8 for 6.8%).",
            },
            "new_rate": {
                "type": "number",
                "description": "Annual interest rate on the new loan (e.g. 6.1 for 6.1%).",
            },
            "balance": {
                "type": "number",
                "description": "Current outstanding loan balance in dollars.",
            },
            "remaining_term": {
                "type": "integer",
                "description": "Remaining term on the existing loan in years.",
            },
            "funding_fee_exempt": {
                "type": "boolean",
                "description": "True if the Veteran is exempt from the IRRRL funding fee.",
            },
        },
        "required": ["current_rate", "new_rate", "balance", "remaining_term"],
    },
}

_APPT_TOOL_DEF = {
    "name": "appointment_scheduler",
    "description": (
        "Schedule a VA loan consultation appointment. Returns a confirmed appointment "
        "slot with a reference number, assigned loan officer, and calendar date."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "preferred_day": {
                "type": "string",
                "description": "Preferred day of the week (e.g. 'Thursday', 'Friday').",
            },
            "preferred_time": {
                "type": "string",
                "description": "Preferred time (e.g. '2:00 PM', 'morning', 'afternoon').",
            },
            "loan_officer": {
                "type": "string",
                "description": "Preferred loan officer name (optional; defaults to next available).",
            },
            "appointment_type": {
                "type": "string",
                "description": "Type of consultation (defaults to 'IRRRL review and rate lock').",
            },
        },
        "required": ["preferred_day", "preferred_time"],
    },
}


class ActionAgent:
    """
    Loan Action Agent powered by Azure AI Foundry new-agent API.

    Uses AIProjectClient.agents.create_version() to register as a new agent
    and the Responses API with a tool call loop for execution.

    Usage::

        agent = ActionAgent()
        await agent.initialize()
        async for event in agent.run(query, refi_input, appt_input):
            process_event(event)
        await agent.close()
    """

    def __init__(self) -> None:
        self._client: AIProjectClient | None = None
        self._agent_version: str | None = None

    @property
    def agent_id(self) -> str:
        """Foundry agent version string — available after initialize()."""
        if self._agent_version is None:
            raise RuntimeError("ActionAgent.initialize() has not been called")
        return self._agent_version

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _get_client(self) -> AIProjectClient:
        if self._client is None:
            self._client = AIProjectClient(
                endpoint=os.environ["PROJECT_ENDPOINT"],
                credential=DefaultAzureCredential(),
            )
        return self._client

    async def initialize(self) -> None:
        """Create or retrieve the Foundry new-agent registration."""
        client = self._get_client()
        model = os.environ["MODEL_DEPLOYMENT_NAME"]

        try:
            existing = await client.agents.get(_AGENT_NAME)
            self._agent_version = existing.versions.latest.version
            logger.info(
                "action_agent: reusing existing Foundry agent '%s' version=%s",
                _AGENT_NAME,
                self._agent_version,
            )
            return
        except ResourceNotFoundError:
            logger.debug("action_agent: no existing agent found — will create new version")

        refi_tool = FunctionTool(
            name=_REFI_TOOL_DEF["name"],
            description=_REFI_TOOL_DEF["description"],
            parameters=_REFI_TOOL_DEF["parameters"],
            strict=False,
        )
        appt_tool = FunctionTool(
            name=_APPT_TOOL_DEF["name"],
            description=_APPT_TOOL_DEF["description"],
            parameters=_APPT_TOOL_DEF["parameters"],
            strict=False,
        )
        version_details = await client.agents.create_version(
            agent_name=_AGENT_NAME,
            description="VA Loan Action Agent — IRRRL savings calculator and appointment scheduler",
            definition=PromptAgentDefinition(
                model=model,
                instructions=ACTION_INSTRUCTIONS,
                tools=[refi_tool, appt_tool],
            ),
        )
        self._agent_version = version_details.version
        logger.info(
            "action_agent: created Foundry agent '%s' version=%s",
            _AGENT_NAME,
            self._agent_version,
        )

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool_call(
        self, name: str, arguments_json: str
    ) -> tuple[str, str]:
        """
        Execute a tool call by name and return (event_message, json_output).

        Called from the tool call loop so we control execution and can emit
        SSE events around it.
        """
        args: dict = json.loads(arguments_json)

        if name == "refi_savings_calculator":
            inputs = RefiCalculatorInput(**args)
            result: RefiCalculatorResult = calculate_refi_savings(inputs)
            benefit = (
                "✓ passes VA net tangible benefit test"
                if result.is_beneficial
                else "✗ fails VA net tangible benefit test"
            )
            message = (
                f"Monthly savings: ${result.monthly_savings:,.2f} | "
                f"Annual savings: ${result.annual_savings:,.2f} | "
                f"Break-even: {result.break_even_months} months | "
                f"{benefit}"
            )
            return message, json.dumps(asdict(result))

        if name == "appointment_scheduler":
            inputs = AppointmentInput(**args)
            result: AppointmentResult = schedule_appointment(inputs)
            message = (
                f"Confirmed: {result.confirmed_day} {result.calendar_date} "
                f"@ {result.confirmed_time} with {result.loan_officer} | "
                f"Ref {result.confirmation_number}"
            )
            return message, json.dumps(asdict(result))

        raise ValueError(f"action_agent: unknown tool '{name}'")

    # ------------------------------------------------------------------
    # Event input formatters
    # ------------------------------------------------------------------

    def _refi_event_inputs(self, refi_input: RefiCalculatorInput) -> dict:
        """Return refi inputs as a plain dict for action_tool_call event emission."""
        return {
            "current_rate": refi_input.current_rate,
            "new_rate": refi_input.new_rate,
            "balance": refi_input.balance,
            "remaining_term": refi_input.remaining_term,
            "funding_fee_exempt": refi_input.funding_fee_exempt,
        }

    def _appt_event_inputs(self, appt_input: AppointmentInput) -> dict:
        """Return appointment inputs as a plain dict for action_tool_call event emission."""
        return {
            "preferred_day": appt_input.preferred_day,
            "preferred_time": appt_input.preferred_time,
        }

    # ------------------------------------------------------------------
    # Prompt builder
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        query: str,
        refi_input: RefiCalculatorInput | None,
        appt_input: AppointmentInput | None,
    ) -> str:
        """
        Construct the user message for the agent run.

        If explicit tool inputs are provided by the orchestrator (demo mode),
        they are included as structured context so the LLM uses the correct
        parameters when calling the tools.
        """
        parts = [query]

        if refi_input is not None:
            parts.append(
                "\n[Loan parameters for the refinance calculation:\n"
                f"  current_rate={refi_input.current_rate}, "
                f"new_rate={refi_input.new_rate}, "
                f"balance={refi_input.balance}, "
                f"remaining_term={refi_input.remaining_term}, "
                f"funding_fee_exempt={refi_input.funding_fee_exempt}]"
            )

        if appt_input is not None:
            parts.append(
                "\n[Appointment parameters:\n"
                f"  preferred_day={appt_input.preferred_day!r}, "
                f"preferred_time={appt_input.preferred_time!r}, "
                f"loan_officer={appt_input.loan_officer!r}, "
                f"appointment_type={appt_input.appointment_type!r}]"
            )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(
        self,
        query: str,
        refi_input: RefiCalculatorInput | None = None,
        appt_input: AppointmentInput | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Execute loan action tools and stream SSE-compatible events.

        Uses the Responses API with the action agent reference and a tool
        call loop: check response.output for function_call items, execute
        each tool locally, and submit results via previous_response_id.

        Yields dicts with at least ``type`` and ``message`` keys.
        The final event has ``type == "_action_text"`` and carries the
        formatted response text; consumed by the orchestrator.
        """
        if refi_input is None and appt_input is None:
            yield {"type": "error", "message": "Action agent requires at least one of: refi_input, appt_input"}
            return

        yield {"type": "action_start", "message": "Loan Action Agent activated"}
        await asyncio.sleep(0.1)

        if not self._agent_version:
            await self.initialize()

        client = self._get_client()
        openai_client = client.get_openai_client()
        model = os.environ["MODEL_DEPLOYMENT_NAME"]
        prompt = self._build_prompt(query, refi_input, appt_input)

        # Maintain explicit conversation history so each API call carries full
        # context — avoids relying on previous_response_id which may not be
        # supported for multi-turn interactions with the Foundry new-agent API.
        conversation: list[dict] = [{"role": "user", "content": prompt}]
        agent_ref = {
            "agent_reference": {
                "name": _AGENT_NAME,
                "version": self._agent_version,
                "type": "agent_reference",
            }
        }

        try:
            response = await openai_client.responses.create(
                model=model,
                input=conversation,
                extra_body=agent_ref,
            )
        except Exception as exc:
            logger.exception("action_agent: failed to start run")
            yield {"type": "error", "message": f"Action agent start error: {exc}"}
            return

        # Tool call loop — process function_call items until none remain.
        while True:
            tool_calls = [
                item for item in (response.output or [])
                if getattr(item, "type", None) == "function_call"
            ]
            if not tool_calls:
                break

            for tc in tool_calls:
                args_dict: dict = json.loads(tc.arguments)
                yield {
                    "type": "action_tool_call",
                    "message": tc.name,
                    "inputs": args_dict,
                }
                await asyncio.sleep(0.35)

                try:
                    result_msg, result_json = self._execute_tool_call(tc.name, tc.arguments)
                    logger.info("action_agent: %s → %s", tc.name, result_msg)
                except Exception as exc:
                    logger.exception(
                        "action_agent: tool execution error for '%s'", tc.name
                    )
                    yield {
                        "type": "error",
                        "message": f"Tool '{tc.name}' error: {exc}",
                    }
                    return

                yield {
                    "type": "action_tool_result",
                    "message": result_msg,
                }
                await asyncio.sleep(0.2)

                # Append the function_call item and its output to the
                # conversation so the next API call has full context.
                conversation.append({
                    "type": "function_call",
                    "call_id": tc.call_id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                })
                conversation.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": result_json,
                })

            try:
                response = await openai_client.responses.create(
                    model=model,
                    input=conversation,
                    extra_body=agent_ref,
                )
            except Exception as exc:
                logger.exception("action_agent: failed to submit tool outputs")
                yield {
                    "type": "error",
                    "message": f"Tool output submission error: {exc}",
                }
                return

        # Internal event carrying the formatted response; consumed by orchestrator.
        response_text: str = response.output_text or ""
        yield {"type": "_action_text", "text": response_text}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release the async HTTP client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
