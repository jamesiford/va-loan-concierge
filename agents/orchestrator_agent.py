"""
VA Loan Concierge — Orchestrator Agent.

Routes each Veteran's query to the appropriate specialized agent(s), collects
their results, and synthesizes a single unified response.

Routing is LLM-driven: the orchestrator Foundry agent classifies each query
via the Responses API to decide which combination of agents to invoke:
  - Advisor Agent    — eligibility, guidelines, FAQ
  - Calculator Agent — refinance savings calculations
  - Scheduler Agent  — appointment booking via custom MCP
  - Calendar Agent   — calendar event creation via Work IQ Calendar

Keyword classification serves as a fallback if the LLM call fails.

The Orchestrator is also registered as a new Azure AI Foundry agent (visible
in the portal) but orchestration itself runs in Python — the "hosted agent"
pattern per Microsoft Foundry documentation.
"""

import asyncio
import json
import logging
import os
from typing import AsyncGenerator

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity.aio import DefaultAzureCredential

from agents.advisor_agent import AdvisorAgent
from agents.calculator_agent import CalculatorAgent
from agents.calendar_agent import CalendarAgent
from agents.scheduler_agent import SchedulerAgent
from profiles import _profile_context_block, _demo_context_block

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

  Loan Calculator (needs_calculator: true)
    — refinance savings calculations, monthly savings, break-even timelines,
      closing costs, VA net tangible benefit test.

  Loan Scheduler (needs_scheduler: true)
    — scheduling/booking an appointment with a loan officer, checking
      availability, creating calendar events, managing meetings.

When asked to classify a query, respond with ONLY a valid JSON object:
  {"needs_advisor": <bool>, "needs_calculator": <bool>, "needs_scheduler": <bool>}

Multiple may be true for mixed queries (e.g. "Am I eligible AND show me my savings
AND book Thursday"). Default needs_advisor to true if the query is ambiguous.
"""

# ---------------------------------------------------------------------------
# Keyword routing helpers (fallback when LLM classification fails)
# ---------------------------------------------------------------------------

_ADVISOR_KEYWORDS: frozenset[str] = frozenset({
    "eligib", "qualify", "can i", "entitlement", "coe", "benefit",
    "requirement", "guideline", "myth", "misconception", "process",
    "step", "faq", "second time", "again", "surviving spouse",
    "discharge", "service-connected", "appraisal", "irrrl", "refinanc",
})

_CALCULATOR_KEYWORDS: frozenset[str] = frozenset({
    "calculat", "saving", "save", "how much", "monthly", "payment",
    "rate", "break-even", "closing cost",
})

_SCHEDULER_KEYWORDS: frozenset[str] = frozenset({
    "schedule", "book", "appointment", "call for", "meeting",
    "calendar", "availab",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
})


def _classify_hint(query: str) -> tuple[bool, bool, bool]:
    """
    Keyword-based pre-classification for routing decisions.
    Defaults to advisor-only if no keywords match.
    """
    q = query.lower()
    needs_advisor = any(kw in q for kw in _ADVISOR_KEYWORDS)
    needs_calculator = any(kw in q for kw in _CALCULATOR_KEYWORDS)
    needs_scheduler = any(kw in q for kw in _SCHEDULER_KEYWORDS)
    if not needs_advisor and not needs_calculator and not needs_scheduler:
        needs_advisor = True
    return needs_advisor, needs_calculator, needs_scheduler


def _route_label(needs_advisor: bool, needs_calculator: bool, needs_scheduler: bool) -> str:
    agents = []
    if needs_advisor:
        agents.append("Advisor Agent")
    if needs_calculator:
        agents.append("Calculator Agent")
    if needs_scheduler:
        agents.append("Scheduler Agent")
    return " + ".join(agents) if agents else "Advisor Agent"


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
        self._calculator: CalculatorAgent | None = None
        self._scheduler: SchedulerAgent | None = None
        self._calendar: CalendarAgent | None = None
        self._orchestrator_version: str | None = None

    def _get_client(self) -> AIProjectClient:
        if self._client is None:
            self._client = AIProjectClient(
                endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                credential=DefaultAzureCredential(),
            )
        return self._client

    async def initialize(self) -> None:
        """
        Initialize sub-agents and register the orchestrator as a new Foundry agent.

        Sub-agents are initialized concurrently (advisor KB connection runs
        in parallel with calculator and scheduler agent registration). The
        orchestrator Foundry registration runs last.
        """
        logger.info("orchestrator: initializing sub-agents")
        self._advisor = AdvisorAgent()
        self._calculator = CalculatorAgent()
        self._scheduler = SchedulerAgent()
        self._calendar = CalendarAgent()

        # Initialize sub-agents concurrently.
        await asyncio.gather(
            self._advisor.initialize(),
            self._calculator.initialize(),
            self._scheduler.initialize(),
            self._calendar.initialize(),
        )
        logger.info("orchestrator: sub-agents ready")

        # Register orchestrator as a new Foundry agent (portal visibility).
        client = self._get_client()
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

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

    async def _llm_classify(self, query: str) -> tuple[bool, bool, bool]:
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
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

        classify_prompt = (
            "Classify the following Veteran's query. Respond with ONLY a JSON object "
            "with three boolean fields — needs_advisor, needs_calculator, and "
            "needs_scheduler — and nothing else.\n\n"
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
            needs_calculator = bool(data.get("needs_calculator", False))
            needs_scheduler = bool(data.get("needs_scheduler", False))
            logger.info(
                "orchestrator: LLM routing — needs_advisor=%s  needs_calculator=%s  needs_scheduler=%s",
                needs_advisor,
                needs_calculator,
                needs_scheduler,
            )
            return needs_advisor, needs_calculator, needs_scheduler
        except Exception as exc:
            logger.warning(
                "orchestrator: LLM classification failed, falling back to keywords: %s", exc
            )
            return _classify_hint(query)

    async def run(
        self, query: str, profile_id: str | None = None
    ) -> AsyncGenerator[dict, None]:
        """
        Orchestrate a query end-to-end, yielding SSE-compatible events.

        Routing is LLM-driven — the orchestrator Foundry agent classifies the
        query via the Responses API, then sub-agents are called directly.
        Keyword classification serves as a fallback if the LLM call fails.
        The final event always has type == 'final_response'.

        profile_id: optional borrower profile key from DEMO_PROFILES.  When
        provided, profile context is prepended to every sub-agent query so the
        agents can give personalised answers.  When None, the agents are
        instructed to gather personal details conversationally.
        """
        if self._advisor is None:
            try:
                await self.initialize()
            except Exception as exc:
                logger.exception("orchestrator: initialization failed")
                yield {"type": "error", "message": f"Initialization error: {exc}"}
                return

        # Build the context-enriched query once — used by all agents.
        profile_ctx = _profile_context_block(profile_id)
        enriched_query = profile_ctx + "\n\n" + query

        # ── Pre-run UX events ────────────────────────────────────────────
        yield {"type": "orchestrator_start", "message": "Analyzing your query..."}
        await asyncio.sleep(0.15)

        needs_advisor, needs_calculator, needs_scheduler = await self._llm_classify(query)
        route_label = _route_label(needs_advisor, needs_calculator, needs_scheduler)
        yield {
            "type": "orchestrator_route",
            "message": f"Routing to: {route_label}",
        }

        # Build the plan chain for the chat thread.
        plan_agents = []
        if needs_advisor:
            plan_agents.append("VA Loan Advisor")
        if needs_calculator:
            plan_agents.append("Loan Calculator")
        if needs_scheduler:
            plan_agents.append("Loan Scheduler")
            plan_agents.append("Calendar")
        yield {
            "type": "plan",
            "message": " → ".join(plan_agents),
        }
        await asyncio.sleep(0.15)

        has_response = False

        # ── Run advisor agent ────────────────────────────────────────────
        advisor_text = ""
        if needs_advisor and self._advisor:
            try:
                async for event in self._advisor.run(enriched_query):
                    if event["type"] == "_advisor_text":
                        advisor_text = event.get("text", "")
                    else:
                        yield event
            except Exception as exc:
                logger.exception("orchestrator: advisor run raised unexpectedly")
                yield {"type": "error", "message": f"Advisor error: {exc}"}
                return

            if advisor_text:
                has_response = True
                yield {
                    "type": "partial_response",
                    "agent": "advisor",
                    "label": "VA Loan Advisor",
                    "content": advisor_text,
                }

        # ── Run calculator agent ─────────────────────────────────────────
        calculator_text = ""
        if needs_calculator and self._calculator:
            if needs_advisor and advisor_text:
                yield {"type": "handoff", "message": "Advisor → Calculator Agent"}

            calculator_query = enriched_query + _demo_context_block(query, profile_id, "calculator")
            try:
                async for event in self._calculator.run(calculator_query):
                    if event["type"] == "_calculator_text":
                        calculator_text = event.get("text", "")
                    else:
                        yield event
            except Exception as exc:
                logger.exception("orchestrator: calculator run raised unexpectedly")
                yield {"type": "error", "message": f"Calculator error: {exc}"}
                return

            if calculator_text:
                has_response = True
                yield {
                    "type": "partial_response",
                    "agent": "calculator",
                    "label": "Loan Calculator",
                    "content": calculator_text,
                }

        # ── Run scheduler agent ──────────────────────────────────────────
        scheduler_text = ""
        if needs_scheduler and self._scheduler:
            if needs_calculator and calculator_text:
                yield {"type": "handoff", "message": "Calculator → Scheduler Agent"}
            elif needs_advisor and advisor_text:
                yield {"type": "handoff", "message": "Advisor → Scheduler Agent"}

            scheduler_query = enriched_query + _demo_context_block(query, profile_id, "scheduler")
            try:
                async for event in self._scheduler.run(scheduler_query):
                    if event["type"] == "_scheduler_text":
                        scheduler_text = event.get("text", "")
                    else:
                        yield event
            except Exception as exc:
                logger.exception("orchestrator: scheduler run raised unexpectedly")
                yield {"type": "error", "message": f"Scheduler error: {exc}"}
                return

            if scheduler_text:
                has_response = True
                yield {
                    "type": "partial_response",
                    "agent": "scheduler",
                    "label": "Loan Scheduler",
                    "content": scheduler_text,
                }

            # ── Run calendar agent (create event) ─────────────────────────
            appointment_json = (
                self._scheduler.extract_appointment_result(self._scheduler.last_response)
                if self._scheduler.last_response
                else None
            )
            if appointment_json and self._calendar:
                yield {"type": "handoff", "message": "Scheduler → Calendar Agent"}

                calendar_query = (
                    f"Call the mcp_CalendarTools_graph_createEvent tool to "
                    f"add this appointment to the Veteran's calendar:\n\n"
                    f"{appointment_json}"
                )
                calendar_text = ""
                try:
                    async for event in self._calendar.run(calendar_query):
                        if event["type"] == "_calendar_text":
                            calendar_text = event.get("text", "")
                        else:
                            yield event
                except Exception as exc:
                    logger.exception("orchestrator: calendar run raised unexpectedly")
                    yield {"type": "error", "message": f"Calendar error: {exc}"}

                if calendar_text:
                    yield {
                        "type": "partial_response",
                        "agent": "calendar",
                        "label": "Calendar",
                        "content": calendar_text,
                    }

        # ── Done ─────────────────────────────────────────────────────────
        if not has_response:
            yield {
                "type": "partial_response",
                "agent": "advisor",
                "label": "VA Loan Concierge",
                "content": "I'm sorry, I couldn't generate a response at this time.",
            }

        yield {"type": "complete", "message": "Response ready"}

    async def close(self) -> None:
        """Release async HTTP clients for all agents."""
        if self._advisor:
            await self._advisor.close()
        if self._calculator:
            await self._calculator.close()
        if self._scheduler:
            await self._scheduler.close()
        if self._calendar:
            await self._calendar.close()
        if self._client:
            await self._client.close()
            self._client = None
        logger.info("orchestrator: closed")
