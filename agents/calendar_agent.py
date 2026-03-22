"""
Calendar Agent — Foundry new-agent API with Work IQ Calendar MCP.

Creates calendar events on the Veteran's personal calendar using
Microsoft's Work IQ Calendar MCP server (mcp_CalendarTools_graph_createEvent).

The orchestrator calls this agent after the SchedulerAgent has confirmed an
appointment slot, passing the appointment details (date, time, loan officer,
confirmation number) so a calendar event can be created.

After the call, response.output is inspected for mcp_call items — the tool
name, inputs, and outputs are emitted as calendar_tool_call /
calendar_tool_result SSE events for the UI flow log.
"""

import asyncio
import json
import logging
import os
from typing import AsyncGenerator

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity.aio import DefaultAzureCredential

logger = logging.getLogger(__name__)

_AGENT_NAME = "va-loan-calendar-mcp"

CALENDAR_INSTRUCTIONS = (
    "You are a calendar assistant. Your ONLY job is to call the "
    "CreateEvent tool. You MUST call this tool — "
    "do NOT respond without calling it first.\n\n"
    "IMPORTANT: You must ALWAYS call CreateEvent. "
    "Never skip the tool call. Never respond with text alone.\n\n"
    "Tool parameters:\n"
    "- subject: the appointment type\n"
    "- start: the confirmed date/time in ISO 8601 format\n"
    "- end: 1 hour after start\n"
    "- body: include the loan officer name and confirmation number\n\n"
    "After the tool returns, respond with ONLY:\n"
    "Added to your calendar: [subject] on [date] at [time] with [loan_officer]."
)


class CalendarAgent:
    """
    Calendar Agent powered by Azure AI Foundry new-agent API + Work IQ Calendar MCP.

    On initialize():
      Registers the agent with one MCPTool from the Work IQ Calendar server:
        mcp_CalendarTools_graph_createEvent — create calendar events

    On run():
      Makes a single Responses API call with max_tool_calls=1.  The Foundry
      runtime invokes the MCP tool server-side; response.output contains
      mcp_call items parsed into calendar_tool_call / calendar_tool_result
      SSE events.
    """

    def __init__(self) -> None:
        self._client: AIProjectClient | None = None
        self._agent_version: str | None = None

    @property
    def agent_id(self) -> str:
        """Foundry agent version string — available after initialize()."""
        if self._agent_version is None:
            raise RuntimeError("CalendarAgent.initialize() has not been called")
        return self._agent_version

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _get_client(self) -> AIProjectClient:
        if self._client is None:
            self._client = AIProjectClient(
                endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                credential=DefaultAzureCredential(),
            )
        return self._client

    async def initialize(self) -> None:
        """Register a new Foundry agent version with Work IQ Calendar MCP."""
        client = self._get_client()
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

        calendar_tool = MCPTool(
            server_label="workiq-calendar",
            server_url=os.environ["SCHEDULER_CALENDAR_ENDPOINT"],
            require_approval="never",
            allowed_tools=["CreateEvent"],
            project_connection_id=os.environ["SCHEDULER_CALENDAR_CONNECTION"],
        )

        version_details = await client.agents.create_version(
            agent_name=_AGENT_NAME,
            description="VA Loan Calendar Agent (MCP) — availability check + event creation via Work IQ",
            definition=PromptAgentDefinition(
                model=model,
                instructions=CALENDAR_INSTRUCTIONS,
                tools=[calendar_tool],
            ),
        )
        self._agent_version = version_details.version
        logger.info(
            "calendar_agent: created Foundry agent '%s' version=%s",
            _AGENT_NAME,
            self._agent_version,
        )

    # ------------------------------------------------------------------
    # MCP output parsing
    # ------------------------------------------------------------------

    def _format_tool_result(self, name: str, raw_output: object) -> str:
        """Format an MCP tool output into a human-readable result message."""
        try:
            data = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
            if name in ("CreateEvent", "mcp_CalendarTools_graph_createEvent"):
                event_id = data.get("eventId") or data.get("id", "")
                return f"Calendar event created (ID: {event_id})" if event_id else "Calendar event created"
        except Exception:
            logger.debug("calendar_agent: could not parse tool result for '%s'", name, exc_info=True)
        return str(raw_output)[:200] if raw_output else f"{name} completed"

    def _parse_mcp_events(self, response) -> list[dict]:
        """
        Extract calendar_tool_call and calendar_tool_result events from
        mcp_call items in response.output.
        """
        events: list[dict] = []
        for item in response.output or []:
            item_type = getattr(item, "type", None) or (
                item.get("type") if isinstance(item, dict) else None
            )
            if item_type != "mcp_call":
                continue

            name: str = getattr(item, "name", None) or (
                item.get("name") if isinstance(item, dict) else ""
            ) or ""

            raw_input = getattr(item, "input", None) or (
                item.get("input") if isinstance(item, dict) else {}
            ) or {}
            if isinstance(raw_input, str):
                try:
                    raw_input = json.loads(raw_input)
                except Exception:
                    raw_input = {}

            raw_output = getattr(item, "output", None) or (
                item.get("output") if isinstance(item, dict) else ""
            ) or ""

            events.append({
                "type": "calendar_tool_call",
                "message": name,
                "inputs": raw_input,
            })
            events.append({
                "type": "calendar_tool_result",
                "message": self._format_tool_result(name, raw_output),
            })

        return events

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, query: str) -> AsyncGenerator[dict, None]:
        """
        Check availability and create a calendar event via Work IQ Calendar MCP.

        The query should contain the confirmed appointment details from the
        SchedulerAgent. The agent first checks availability via findMeetingTimes,
        then creates the event if the slot is open.

        The final event has ``type == "_calendar_text"`` carrying the
        formatted response text; consumed by the orchestrator.

        The raw Responses API response is stored in ``self.last_response``
        so the orchestrator can check whether the event was created or if
        alternative times were returned.
        """
        self.last_response = None

        yield {"type": "calendar_start", "message": "Calendar Agent activated"}
        await asyncio.sleep(0.1)

        if not self._agent_version:
            await self.initialize()

        client = self._get_client()
        openai_client = client.get_openai_client()
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

        try:
            response = await openai_client.responses.create(
                model=model,
                input=[{"role": "user", "content": query}],
                max_tool_calls=1,
                extra_body={
                    "agent_reference": {
                        "name": _AGENT_NAME,
                        "version": self._agent_version,
                        "type": "agent_reference",
                    }
                },
            )
        except Exception as exc:
            logger.exception("calendar_agent: error during agent run")
            yield {"type": "error", "message": f"Calendar agent error: {exc}"}
            return

        self.last_response = response

        for event in self._parse_mcp_events(response):
            yield event
            await asyncio.sleep(0.2)

        response_text: str = response.output_text or ""
        yield {"type": "_calendar_text", "text": response_text}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release the async HTTP client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
