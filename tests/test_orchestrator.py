"""
Tests for the Orchestrator.

Covers:
  - _classify_hint routing logic (3-way: advisor/calculator/scheduler)
  - _demo_context_block parameter injection (target_agent split)
  - _route_label label generation
  - Orchestrator.run() end-to-end event sequence (mocked sub-agents)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.orchestrator_agent import (
    _classify_hint,
    _route_label,
    Orchestrator,
)
from profiles import _demo_context_block


# ---------------------------------------------------------------------------
# Helper: mock _llm_classify to use keyword fallback (no Azure client needed)
# ---------------------------------------------------------------------------

def _patch_llm_classify(orch: Orchestrator) -> None:
    """Replace _llm_classify with a keyword-based stub for testing."""
    async def _stub(query: str) -> tuple[bool, bool, bool]:
        return _classify_hint(query)
    orch._llm_classify = _stub


# ---------------------------------------------------------------------------
# _classify_hint
# ---------------------------------------------------------------------------

class TestClassifyHint:
    def test_irrrl_eligibility_query_is_advisor_only(self):
        advisor, calculator, scheduler = _classify_hint("Am I eligible for an IRRRL?")
        assert advisor is True
        assert calculator is False
        assert scheduler is False

    def test_second_time_query_is_advisor_only(self):
        advisor, calculator, scheduler = _classify_hint("Can I use my VA loan a second time?")
        assert advisor is True
        assert calculator is False
        assert scheduler is False

    def test_schedule_query_is_scheduler(self):
        advisor, calculator, scheduler = _classify_hint("Book a call for Thursday")
        assert scheduler is True

    def test_calculation_query_is_calculator(self):
        advisor, calculator, scheduler = _classify_hint("How much would I save by refinancing?")
        assert calculator is True

    def test_flagship_mixed_query_triggers_all(self):
        query = (
            "I'm thinking about refinancing my VA loan. Am I eligible for an IRRRL, "
            "and can you show me what I'd save and schedule a call for Thursday?"
        )
        advisor, calculator, scheduler = _classify_hint(query)
        assert advisor is True
        assert calculator is True
        assert scheduler is True

    def test_unknown_query_defaults_to_advisor(self):
        advisor, calculator, scheduler = _classify_hint("Hello there")
        assert advisor is True
        assert calculator is False
        assert scheduler is False

    def test_route_label_all(self):
        assert _route_label(True, True, True) == "Advisor Agent + Calculator Agent + Scheduler Agent"

    def test_route_label_advisor_calculator(self):
        assert _route_label(True, True, False) == "Advisor Agent + Calculator Agent"

    def test_route_label_advisor_only(self):
        assert _route_label(True, False, False) == "Advisor Agent"

    def test_route_label_scheduler_only(self):
        assert _route_label(False, False, True) == "Scheduler Agent"

    def test_route_label_calculator_scheduler(self):
        assert _route_label(False, True, True) == "Calculator Agent + Scheduler Agent"


# ---------------------------------------------------------------------------
# _demo_context_block
# ---------------------------------------------------------------------------

class TestDemoContextBlock:
    def test_calculator_target_includes_loan_params(self):
        block = _demo_context_block("I want to refinance my VA loan", profile_id="marcus", target_agent="calculator")
        assert "6.8" in block
        assert "6.1" in block
        assert "320000" in block

    def test_scheduler_target_includes_appointment_params(self):
        block = _demo_context_block("Book a call for Thursday", profile_id="marcus", target_agent="scheduler")
        assert "appointment_scheduler" in block

    def test_calculator_target_excludes_scheduling(self):
        block = _demo_context_block("Book a call for Thursday", profile_id="marcus", target_agent="calculator")
        assert block == ""

    def test_scheduler_target_excludes_loan_params(self):
        block = _demo_context_block("I want to refinance my VA loan", profile_id="marcus", target_agent="scheduler")
        assert block == ""

    def test_unrelated_query_returns_empty(self):
        block = _demo_context_block("What is the VA loan funding fee waiver?", profile_id="marcus", target_agent="calculator")
        assert block == ""

    def test_funding_fee_exempt_flag_included(self):
        block = _demo_context_block("Calculate my IRRRL savings", profile_id="marcus", target_agent="calculator")
        assert "funding_fee_exempt" in block


# ---------------------------------------------------------------------------
# Orchestrator.run() — end-to-end (mocked sub-agents)
# ---------------------------------------------------------------------------

def _make_orchestrator_with_mocks(
    advisor_events: tuple = (),
    calculator_events: tuple = (),
    scheduler_events: tuple = (),
    calendar_events: tuple = (),
) -> Orchestrator:
    """
    Return an Orchestrator with all sub-agents replaced by async generator mocks
    and _llm_classify patched to use keyword-based routing (no Azure client needed).
    """
    orch = Orchestrator()

    async def _advisor_run(query: str):
        for event in advisor_events:
            yield event

    async def _calculator_run(query: str):
        for event in calculator_events:
            yield event

    async def _scheduler_run(query: str):
        for event in scheduler_events:
            yield event

    async def _calendar_run(query: str):
        for event in calendar_events:
            yield event

    advisor = MagicMock()
    advisor.run = _advisor_run
    calculator = MagicMock()
    calculator.run = _calculator_run
    scheduler = MagicMock()
    scheduler.run = _scheduler_run
    scheduler.last_response = None
    scheduler.extract_appointment_result = MagicMock(return_value=None)
    calendar = MagicMock()
    calendar.run = _calendar_run
    calendar.last_response = MagicMock()

    orch._advisor = advisor
    orch._calculator = calculator
    orch._scheduler = scheduler
    orch._calendar = calendar
    orch._orchestrator_version = "1"  # skip initialize()
    _patch_llm_classify(orch)         # keyword stub — no Azure client

    return orch


async def collect_events(orch: Orchestrator, query: str) -> list[dict]:
    return [e async for e in orch.run(query)]


class TestOrchestratorRun:
    async def test_orchestrator_start_is_first_event(self):
        orch = _make_orchestrator_with_mocks()
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        assert events[0]["type"] == "orchestrator_start"

    async def test_orchestrator_route_is_second_event(self):
        orch = _make_orchestrator_with_mocks()
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        assert events[1]["type"] == "orchestrator_route"

    async def test_complete_is_last_event(self):
        orch = _make_orchestrator_with_mocks()
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        assert events[-1]["type"] == "complete"

    async def test_partial_response_emitted_before_complete(self):
        advisor_events = (
            {"type": "_advisor_text", "text": "You are eligible."},
        )
        orch = _make_orchestrator_with_mocks(advisor_events=advisor_events)
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        types = [e["type"] for e in events]
        assert "partial_response" in types
        assert "complete" in types
        assert types.index("partial_response") < types.index("complete")

    async def test_advisor_events_forwarded(self):
        """Events from advisor run (except _advisor_text) appear in output."""
        advisor_events = (
            {"type": "advisor_start", "message": "VA Loan Advisor activated"},
            {"type": "advisor_result", "message": "Answer ready"},
            {"type": "_advisor_text", "text": "You are eligible."},
        )
        orch = _make_orchestrator_with_mocks(advisor_events=advisor_events)
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        types = [e["type"] for e in events]
        assert "advisor_start" in types
        assert "advisor_result" in types
        assert "_advisor_text" not in types

    async def test_calculator_events_forwarded(self):
        """Events from calculator run (except _calculator_text) appear in output."""
        calculator_events = (
            {"type": "calculator_start", "message": "Loan Calculator Agent activated"},
            {"type": "calculator_tool_call", "message": "refi_savings_calculator", "inputs": {}},
            {"type": "calculator_tool_result", "message": "Monthly savings: $142"},
            {"type": "_calculator_text", "text": "Your savings are $142/month."},
        )
        orch = _make_orchestrator_with_mocks(calculator_events=calculator_events)
        events = await collect_events(orch, "How much would I save by refinancing?")
        types = [e["type"] for e in events]
        assert "calculator_start" in types
        assert "calculator_tool_call" in types
        assert "calculator_tool_result" in types
        assert "_calculator_text" not in types

    async def test_scheduler_events_forwarded(self):
        """Events from scheduler run (except _scheduler_text) appear in output."""
        scheduler_events = (
            {"type": "scheduler_start", "message": "Loan Scheduler Agent activated"},
            {"type": "scheduler_tool_call", "message": "appointment_scheduler", "inputs": {}},
            {"type": "scheduler_tool_result", "message": "Confirmed: Thu Mar 26"},
            {"type": "_scheduler_text", "text": "Your appointment is confirmed."},
        )
        orch = _make_orchestrator_with_mocks(scheduler_events=scheduler_events)
        events = await collect_events(orch, "Book a call for Thursday")
        types = [e["type"] for e in events]
        assert "scheduler_start" in types
        assert "scheduler_tool_call" in types
        assert "_scheduler_text" not in types

    async def test_advisor_text_in_partial_response(self):
        advisor_events = (
            {"type": "_advisor_text", "text": "You are eligible for IRRRL."},
        )
        orch = _make_orchestrator_with_mocks(advisor_events=advisor_events)
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        partials = [e for e in events if e["type"] == "partial_response"]
        assert len(partials) == 1
        assert "You are eligible for IRRRL." in partials[0]["content"]
        assert partials[0]["agent"] == "advisor"
        assert partials[0]["label"] == "VA Loan Advisor"

    async def test_calculator_text_in_partial_response(self):
        calculator_events = (
            {"type": "_calculator_text", "text": "Monthly savings: $142."},
        )
        orch = _make_orchestrator_with_mocks(calculator_events=calculator_events)
        events = await collect_events(orch, "How much would I save by refinancing?")
        partials = [e for e in events if e["type"] == "partial_response"]
        assert len(partials) == 1
        assert "Monthly savings: $142." in partials[0]["content"]
        assert partials[0]["agent"] == "calculator"

    async def test_all_agents_emit_separate_partials(self):
        """Each agent emits its own partial_response event."""
        advisor_events = (
            {"type": "_advisor_text", "text": "You are eligible."},
        )
        calculator_events = (
            {"type": "_calculator_text", "text": "Monthly savings: $142."},
        )
        scheduler_events = (
            {"type": "_scheduler_text", "text": "Appointment confirmed."},
        )
        query = (
            "Am I eligible for an IRRRL and can you show me my savings "
            "and schedule a call for Thursday?"
        )
        orch = _make_orchestrator_with_mocks(
            advisor_events=advisor_events,
            calculator_events=calculator_events,
            scheduler_events=scheduler_events,
        )
        events = await collect_events(orch, query)
        partials = [e for e in events if e["type"] == "partial_response"]
        assert len(partials) == 3
        assert partials[0]["agent"] == "advisor"
        assert partials[1]["agent"] == "calculator"
        assert partials[2]["agent"] == "scheduler"
        assert "You are eligible." in partials[0]["content"]
        assert "Monthly savings: $142." in partials[1]["content"]
        assert "Appointment confirmed." in partials[2]["content"]

    async def test_handoff_events_emitted(self):
        """Handoff events are emitted when transitioning between agents."""
        advisor_events = (
            {"type": "_advisor_text", "text": "You are eligible."},
        )
        calculator_events = (
            {"type": "_calculator_text", "text": "Monthly savings: $142."},
        )
        scheduler_events = (
            {"type": "_scheduler_text", "text": "Confirmed."},
        )
        query = (
            "Am I eligible for an IRRRL and can you show me my savings "
            "and schedule a call for Thursday?"
        )
        orch = _make_orchestrator_with_mocks(
            advisor_events=advisor_events,
            calculator_events=calculator_events,
            scheduler_events=scheduler_events,
        )
        events = await collect_events(orch, query)
        handoffs = [e for e in events if e["type"] == "handoff"]
        assert len(handoffs) >= 1

    async def test_error_events_from_advisor_forwarded(self):
        advisor_events = (
            {"type": "error", "message": "Something went wrong"},
        )
        orch = _make_orchestrator_with_mocks(advisor_events=advisor_events)
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        assert any(e["type"] == "error" for e in events)


# ---------------------------------------------------------------------------
# _llm_classify — LLM-driven routing
# ---------------------------------------------------------------------------

class TestLlmClassify:
    def _make_orch_with_responses(self, response_json: str) -> Orchestrator:
        """Return an Orchestrator whose openai_client returns the given JSON string."""
        orch = Orchestrator()
        orch._orchestrator_version = "1"

        openai_client = MagicMock()
        response = MagicMock()
        response.output_text = response_json
        openai_client.responses.create = AsyncMock(return_value=response)

        mock_client = MagicMock()
        mock_client.get_openai_client = MagicMock(return_value=openai_client)
        orch._get_client = lambda: mock_client

        return orch

    async def test_advisor_only_from_llm(self):
        orch = self._make_orch_with_responses(
            '{"needs_advisor": true, "needs_calculator": false, "needs_scheduler": false}'
        )
        advisor, calculator, scheduler = await orch._llm_classify("Am I eligible for an IRRRL?")
        assert advisor is True
        assert calculator is False
        assert scheduler is False

    async def test_calculator_only_from_llm(self):
        orch = self._make_orch_with_responses(
            '{"needs_advisor": false, "needs_calculator": true, "needs_scheduler": false}'
        )
        advisor, calculator, scheduler = await orch._llm_classify("Show me my savings")
        assert advisor is False
        assert calculator is True
        assert scheduler is False

    async def test_scheduler_only_from_llm(self):
        orch = self._make_orch_with_responses(
            '{"needs_advisor": false, "needs_calculator": false, "needs_scheduler": true}'
        )
        advisor, calculator, scheduler = await orch._llm_classify("Book a call for Thursday")
        assert advisor is False
        assert calculator is False
        assert scheduler is True

    async def test_all_from_llm(self):
        orch = self._make_orch_with_responses(
            '{"needs_advisor": true, "needs_calculator": true, "needs_scheduler": true}'
        )
        advisor, calculator, scheduler = await orch._llm_classify("Flagship query")
        assert advisor is True
        assert calculator is True
        assert scheduler is True

    async def test_markdown_fenced_json_parsed(self):
        orch = self._make_orch_with_responses(
            '```json\n{"needs_advisor": true, "needs_calculator": true, "needs_scheduler": false}\n```'
        )
        advisor, calculator, scheduler = await orch._llm_classify("Flagship query")
        assert advisor is True
        assert calculator is True

    async def test_llm_failure_falls_back_to_keywords(self):
        orch = Orchestrator()
        orch._orchestrator_version = "1"

        openai_client = MagicMock()
        openai_client.responses.create = AsyncMock(side_effect=Exception("quota_exceeded"))
        mock_client = MagicMock()
        mock_client.get_openai_client = MagicMock(return_value=openai_client)
        orch._get_client = lambda: mock_client

        advisor, calculator, scheduler = await orch._llm_classify("Am I eligible for an IRRRL?")
        assert advisor is True
        assert calculator is False

    async def test_no_version_uses_keyword_fallback(self):
        orch = Orchestrator()
        assert orch._orchestrator_version is None
        advisor, calculator, scheduler = await orch._llm_classify("Book a call for Thursday")
        assert scheduler is True
