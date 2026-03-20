"""
VA Loan Concierge — Orchestrator

Routes each Veteran's query to the appropriate specialized agent(s), collects
their results, and synthesizes a single unified response.

Routing is LLM-driven: the orchestrator Foundry agent classifies each query
via the Responses API to decide whether to invoke the Advisor Agent, the
Action Agent, or both. Keyword classification serves as a fallback if the
LLM call fails.

Can be used two ways:
  1. CLI:  python main.py [--query "..."]
  2. API:  import and instantiate Orchestrator; call .run() from server.py
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import AsyncGenerator

from dotenv import load_dotenv

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential

from agents.advisor_agent import AdvisorAgent
from agents.action_agent import ActionAgent
from tools.refi_calculator import RefiCalculatorInput
from tools.appointment_scheduler import AppointmentInput

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Orchestrator agent definition (registered as new Foundry agent)
# ---------------------------------------------------------------------------

# URL-safe agent name (alphanumeric + hyphens, max 63 chars).
_ORCHESTRATOR_NAME = "va-loan-orchestrator"

ORCHESTRATOR_INSTRUCTIONS = """\
You are the VA Loan Concierge — a routing coordinator for a VA mortgage lender.

Your primary job is to classify each Veteran's query and decide which specialist
agent(s) to invoke:

  VA Loan Advisor (needs_advisor: true)
    — eligibility questions, IRRRL qualification, VA loan benefits, entitlement,
      funding fee rules, property requirements, loan process steps, FAQ, myths,
      second-time use, surviving spouse rules, or anything the Veteran needs to
      understand before taking action.

  Loan Action Agent (needs_action: true)
    — refinance savings calculations, monthly savings, break-even timelines,
      closing costs, VA net tangible benefit test, or scheduling/booking an
      appointment with a loan officer.

When asked to classify a query, respond with ONLY a valid JSON object:
  {"needs_advisor": <bool>, "needs_action": <bool>}

Both may be true for mixed queries (e.g. "Am I eligible AND show me my savings
AND book Thursday"). Default needs_advisor to true if the query is ambiguous.
"""

# ---------------------------------------------------------------------------
# Demo scenario — flagship query and hardcoded loan parameters
# ---------------------------------------------------------------------------

FLAGSHIP_QUERY = (
    "I'm thinking about refinancing my VA loan. Am I eligible for an IRRRL, "
    "and can you show me what I'd save and schedule a call for Thursday?"
)

# Hardcoded demo loan parameters — funding_fee_exempt=True (service-connected
# disability) gives a 29-month break-even that passes the VA net tangible
# benefit test. The orchestrator passes these to the action agent so the
# demo always uses the correct numbers.
DEMO_REFI_INPUT = RefiCalculatorInput(
    current_rate=6.8,
    new_rate=6.1,
    balance=320_000,
    remaining_term=27,
    funding_fee_exempt=True,
)

DEMO_APPT_INPUT = AppointmentInput(
    preferred_day="Thursday",
    preferred_time="2:00 PM",
)

# ---------------------------------------------------------------------------
# Pre-run UX hints (keyword-based — emitted before agent execution)
# ---------------------------------------------------------------------------
# These are used to give the UI something to render immediately while the
# agents work. They are keyword-based hints, not the authoritative routing
# decision — actual routing runs agent invocations based on the same keywords.

_ADVISOR_KEYWORDS: frozenset[str] = frozenset({
    "eligib", "qualify", "can i", "entitlement", "coe", "benefit",
    "requirement", "guideline", "myth", "misconception", "process",
    "step", "faq", "second time", "again", "surviving spouse",
    "discharge", "service-connected", "appraisal", "irrrl", "refinanc",
})

_ACTION_KEYWORDS: frozenset[str] = frozenset({
    "calculat", "saving", "save", "how much", "schedule", "book",
    "appointment", "call for", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "monthly", "payment", "rate",
    "break-even", "closing cost",
})


def _classify_hint(query: str) -> tuple[bool, bool]:
    """
    Keyword-based pre-classification for routing decisions.
    Defaults to advisor-only if no keywords match.
    """
    q = query.lower()
    needs_advisor = any(kw in q for kw in _ADVISOR_KEYWORDS)
    needs_action = any(kw in q for kw in _ACTION_KEYWORDS)
    if not needs_advisor and not needs_action:
        needs_advisor = True
    return needs_advisor, needs_action


def _route_label(needs_advisor: bool, needs_action: bool) -> str:
    if needs_advisor and needs_action:
        return "Advisor Agent + Action Agent"
    if needs_advisor:
        return "Advisor Agent"
    return "Action Agent"



def _demo_context_block(query: str) -> str:
    """
    Build a structured context block with demo loan parameters when the
    query involves calculations or scheduling.

    In a production deployment these would come from the borrower's loan
    profile or be extracted from conversation history.
    """
    q = query.lower()
    parts: list[str] = []

    if any(kw in q for kw in ("calculat", "saving", "save", "how much", "refinanc", "irrrl")):
        parts.append(
            "[Loan parameters for the refinance calculation — "
            "pass these exactly to the refi_savings_calculator:\n"
            f"  current_rate={DEMO_REFI_INPUT.current_rate}, "
            f"new_rate={DEMO_REFI_INPUT.new_rate}, "
            f"balance={DEMO_REFI_INPUT.balance}, "
            f"remaining_term={DEMO_REFI_INPUT.remaining_term}, "
            f"funding_fee_exempt={DEMO_REFI_INPUT.funding_fee_exempt} "
            "(Veteran has service-connected disability)]"
        )

    if any(kw in q for kw in ("schedule", "book", "appointment", "call for",
                               "monday", "tuesday", "wednesday", "thursday",
                               "friday", "saturday")):
        parts.append(
            "[Appointment parameters — pass these exactly to appointment_scheduler:\n"
            f"  preferred_day={DEMO_APPT_INPUT.preferred_day!r}, "
            f"preferred_time={DEMO_APPT_INPUT.preferred_time!r}]"
        )

    return "\n\n" + "\n".join(parts) if parts else ""


def _demo_action_inputs(
    query: str,
) -> tuple[RefiCalculatorInput | None, AppointmentInput | None]:
    """
    Return demo RefiCalculatorInput and AppointmentInput based on query keywords.
    Both may be None if the query doesn't match the relevant keywords.
    """
    q = query.lower()
    refi = (
        DEMO_REFI_INPUT
        if any(kw in q for kw in ("calculat", "saving", "save", "how much", "refinanc", "irrrl"))
        else None
    )
    appt = (
        DEMO_APPT_INPUT
        if any(kw in q for kw in ("schedule", "book", "appointment", "call for",
                                   "monday", "tuesday", "wednesday", "thursday",
                                   "friday", "saturday"))
        else None
    )
    return refi, appt


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    VA Loan Concierge orchestrator.

    Uses Python-level routing — calls sub-agents directly and forwards their
    events to the client in real time. Also registered as a new Azure AI
    Foundry agent (visible in the portal) but orchestration runs in Python.

    Instantiate once and reuse across multiple queries (the API server
    holds a single instance). Call initialize() before the first run().

    Usage::

        orch = Orchestrator()
        await orch.initialize()
        async for event in orch.run(query):
            send_to_client(event)
        await orch.close()
    """

    def __init__(self) -> None:
        self._client: AIProjectClient | None = None
        self._advisor: AdvisorAgent | None = None
        self._action: ActionAgent | None = None
        self._orchestrator_version: str | None = None

    def _get_client(self) -> AIProjectClient:
        if self._client is None:
            self._client = AIProjectClient(
                endpoint=os.environ["PROJECT_ENDPOINT"],
                credential=DefaultAzureCredential(),
            )
        return self._client

    async def initialize(self) -> None:
        """
        Initialize sub-agents and register the orchestrator as a new Foundry agent.

        Sub-agents are initialized concurrently (advisor file upload runs
        in parallel with action agent registration). The orchestrator Foundry
        registration runs last.

        On subsequent calls, existing agents are reused — no re-upload or
        re-creation occurs.
        """
        logger.info("orchestrator: initializing sub-agents")
        self._advisor = AdvisorAgent()
        self._action = ActionAgent()

        # Initialize sub-agents concurrently.
        await asyncio.gather(
            self._advisor.initialize(),
            self._action.initialize(),
        )
        logger.info("orchestrator: sub-agents ready")

        # Register orchestrator as a new Foundry agent (portal visibility).
        client = self._get_client()
        model = os.environ["MODEL_DEPLOYMENT_NAME"]

        try:
            existing = await client.agents.get(_ORCHESTRATOR_NAME)
            self._orchestrator_version = existing.versions.latest.version
            logger.info(
                "orchestrator: reusing Foundry agent '%s' version=%s",
                _ORCHESTRATOR_NAME,
                self._orchestrator_version,
            )
            return
        except ResourceNotFoundError:
            logger.debug("orchestrator: no existing agent found — will create new version")

        version_details = await client.agents.create_version(
            agent_name=_ORCHESTRATOR_NAME,
            description="VA Loan Concierge — multi-agent orchestrator",
            definition=PromptAgentDefinition(
                model=model,
                instructions=ORCHESTRATOR_INSTRUCTIONS,
            ),
        )
        self._orchestrator_version = version_details.version
        logger.info(
            "orchestrator: created Foundry agent '%s' version=%s",
            _ORCHESTRATOR_NAME,
            self._orchestrator_version,
        )

    async def _llm_classify(self, query: str) -> tuple[bool, bool]:
        """
        Use the orchestrator Foundry agent to classify routing via LLM inference.

        Calls the Responses API with a structured classification prompt and
        parses the JSON routing decision. Falls back to keyword classification
        if the LLM call fails or returns unparseable output.
        """
        if not self._orchestrator_version:
            logger.debug("orchestrator: no version set — using keyword fallback")
            return _classify_hint(query)

        client = self._get_client()
        openai_client = client.get_openai_client()
        model = os.environ["MODEL_DEPLOYMENT_NAME"]

        classify_prompt = (
            "Classify the following Veteran's query. Respond with ONLY a JSON object "
            "with two boolean fields — needs_advisor and needs_action — and nothing else.\n\n"
            f'Query: "{query}"'
        )

        try:
            response = await openai_client.responses.create(
                model=model,
                input=[{"role": "user", "content": classify_prompt}],
                extra_body={
                    "agent_reference": {
                        "name": _ORCHESTRATOR_NAME,
                        "version": self._orchestrator_version,
                        "type": "agent_reference",
                    }
                },
            )
            text = (response.output_text or "").strip()
            # Strip markdown code fences if the model wraps the JSON.
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            needs_advisor = bool(data.get("needs_advisor", True))
            needs_action = bool(data.get("needs_action", False))
            logger.info(
                "orchestrator: LLM routing decision — needs_advisor=%s  needs_action=%s",
                needs_advisor,
                needs_action,
            )
            return needs_advisor, needs_action
        except Exception as exc:
            logger.warning(
                "orchestrator: LLM classification failed, falling back to keywords: %s", exc
            )
            return _classify_hint(query)

    async def run(self, query: str) -> AsyncGenerator[dict, None]:
        """
        Orchestrate a query end-to-end, yielding SSE-compatible events.

        Routing is LLM-driven — the orchestrator Foundry agent classifies the
        query via the Responses API, then sub-agents are called directly.
        Keyword classification serves as a fallback if the LLM call fails.
        The final event always has type == 'final_response'.
        """
        if self._advisor is None:
            try:
                await self.initialize()
            except Exception as exc:
                logger.exception("orchestrator: initialization failed")
                yield {"type": "error", "message": f"Initialization error: {exc}"}
                return

        # ── Pre-run UX events ────────────────────────────────────────────
        yield {"type": "orchestrator_start", "message": "Analyzing your query..."}
        await asyncio.sleep(0.15)

        needs_advisor, needs_action = await self._llm_classify(query)
        yield {
            "type": "orchestrator_route",
            "message": f"Routing to: {_route_label(needs_advisor, needs_action)}",
        }
        await asyncio.sleep(0.15)

        # ── Run advisor agent ────────────────────────────────────────────
        advisor_text = ""
        if needs_advisor and self._advisor:
            try:
                async for event in self._advisor.run(query):
                    if event["type"] == "_advisor_text":
                        advisor_text = event.get("text", "")
                    else:
                        yield event
            except Exception as exc:
                logger.exception("orchestrator: advisor run raised unexpectedly")
                yield {"type": "error", "message": f"Advisor error: {exc}"}
                return

        # ── Handoff and action agent ─────────────────────────────────────
        action_text = ""
        if needs_action and self._action:
            if needs_advisor and advisor_text:
                yield {"type": "handoff", "message": "Advisor → Action Agent"}

            refi_input, appt_input = _demo_action_inputs(query)
            try:
                async for event in self._action.run(query, refi_input, appt_input):
                    if event["type"] == "_action_text":
                        action_text = event.get("text", "")
                    else:
                        yield event
            except Exception as exc:
                logger.exception("orchestrator: action run raised unexpectedly")
                yield {"type": "error", "message": f"Action error: {exc}"}
                return

        # ── Synthesize and emit final response ──────────────────────────
        yield {
            "type": "orchestrator_synthesize",
            "message": "Synthesizing final response...",
        }

        response_parts: list[str] = []
        if advisor_text:
            response_parts.append(advisor_text)
        if action_text:
            response_parts.append(action_text)
        final_text = (
            "\n\n".join(response_parts)
            if response_parts
            else "I'm sorry, I couldn't generate a response at this time."
        )

        yield {"type": "complete", "message": "Response ready"}
        yield {"type": "final_response", "content": final_text}

    async def close(self) -> None:
        """Release async HTTP clients for all agents."""
        if self._advisor:
            await self._advisor.close()
        if self._action:
            await self._action.close()
        if self._client:
            await self._client.close()
            self._client = None
        logger.info("orchestrator: closed")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_EVENT_PREFIXES: dict[str, str] = {
    "orchestrator_start":      "⬡  Orchestrator",
    "orchestrator_route":      "→  Orchestrator",
    "advisor_start":           "📚 Advisor",
    "advisor_source":          "🔍 Advisor",
    "advisor_result":          "✓  Advisor",
    "action_start":            "⚙️  Action",
    "action_tool_call":        "🔧 Action",
    "action_tool_result":      "✓  Action",
    "handoff":                 "⇄  Handoff",
    "orchestrator_synthesize": "⬡  Orchestrator",
    "complete":                "✓  Complete",
    "error":                   "✗  Error",
}

_DIVIDER = "─" * 60


def _print_event(event: dict) -> None:
    etype = event.get("type", "")

    if etype == "final_response":
        print(f"\n{_DIVIDER}")
        print("  VA LOAN CONCIERGE RESPONSE")
        print(_DIVIDER)
        print(event.get("content", ""))
        print(_DIVIDER)
        return

    prefix = _EVENT_PREFIXES.get(etype, f"   {etype}")
    message = event.get("message", "")

    if etype == "action_tool_call":
        inputs = event.get("inputs", {})
        inputs_str = ",  ".join(f"{k}={v}" for k, v in inputs.items())
        print(f"  {prefix}: {message}")
        if inputs_str:
            print(f"           {inputs_str}")
    else:
        print(f"  {prefix}: {message}")


async def _cli_main(query: str) -> None:
    print(f"\n{_DIVIDER}")
    print("  VA LOAN CONCIERGE — DEMO")
    print(_DIVIDER)
    print(f"  Query: {query}")
    print(_DIVIDER)
    print()

    orchestrator = Orchestrator()
    try:
        await orchestrator.initialize()
        async for event in orchestrator.run(query):
            _print_event(event)
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VA Loan Concierge — multi-agent demo (CLI mode)"
    )
    parser.add_argument(
        "--query",
        default=FLAGSHIP_QUERY,
        help="Question to send to the concierge (default: flagship IRRRL demo query)",
    )
    args = parser.parse_args()
    asyncio.run(_cli_main(args.query))
