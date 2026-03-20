"""
Tests for the Orchestrator.

Covers:
  - _classify_hint routing logic
  - _demo_context_block parameter injection
  - _route_label label generation
  - Orchestrator.run() end-to-end event sequence (mocked sub-agents)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from main import (
    _classify_hint,
    _demo_context_block,
    _route_label,
    Orchestrator,
    DEMO_REFI_INPUT,
    DEMO_APPT_INPUT,
)


# ---------------------------------------------------------------------------
# Helper: mock _llm_classify to use keyword fallback (no Azure client needed)
# ---------------------------------------------------------------------------

def _patch_llm_classify(orch: Orchestrator) -> None:
    """Replace _llm_classify with a keyword-based stub for testing."""
    async def _stub(query: str) -> tuple[bool, bool]:
        return _classify_hint(query)
    orch._llm_classify = _stub


# ---------------------------------------------------------------------------
# _classify_hint
# ---------------------------------------------------------------------------

class TestClassifyHint:
    def test_irrrl_eligibility_query_is_advisor_only(self):
        advisor, action = _classify_hint("Am I eligible for an IRRRL?")
        assert advisor is True
        assert action is False

    def test_second_time_query_is_advisor_only(self):
        advisor, action = _classify_hint("Can I use my VA loan a second time?")
        assert advisor is True
        assert action is False

    def test_schedule_query_is_action_only(self):
        advisor, action = _classify_hint("Book a call for Thursday")
        assert action is True

    def test_flagship_mixed_query_triggers_both(self):
        query = (
            "I'm thinking about refinancing my VA loan. Am I eligible for an IRRRL, "
            "and can you show me what I'd save and schedule a call for Thursday?"
        )
        advisor, action = _classify_hint(query)
        assert advisor is True
        assert action is True

    def test_unknown_query_defaults_to_advisor(self):
        advisor, action = _classify_hint("Hello there")
        assert advisor is True
        assert action is False

    def test_calculation_query_is_action(self):
        advisor, action = _classify_hint("How much would I save by refinancing?")
        assert action is True

    def test_route_label_both(self):
        assert _route_label(True, True) == "Advisor Agent + Action Agent"

    def test_route_label_advisor_only(self):
        assert _route_label(True, False) == "Advisor Agent"

    def test_route_label_action_only(self):
        assert _route_label(False, True) == "Action Agent"


# ---------------------------------------------------------------------------
# _demo_context_block
# ---------------------------------------------------------------------------

class TestDemoContextBlock:
    def test_refinance_query_includes_loan_params(self):
        block = _demo_context_block("I want to refinance my VA loan")
        assert str(DEMO_REFI_INPUT.current_rate) in block
        assert str(DEMO_REFI_INPUT.new_rate) in block
        assert str(DEMO_REFI_INPUT.balance) in block

    def test_thursday_query_includes_appointment_params(self):
        block = _demo_context_block("Book a call for Thursday")
        assert "Thursday" in block
        assert "2:00 PM" in block

    def test_flagship_query_includes_both_blocks(self):
        query = (
            "Am I eligible for an IRRRL and can you show me my savings "
            "and schedule a call for Thursday?"
        )
        block = _demo_context_block(query)
        assert str(DEMO_REFI_INPUT.current_rate) in block
        assert "Thursday" in block

    def test_unrelated_query_returns_empty(self):
        block = _demo_context_block("What is the VA loan funding fee waiver?")
        assert block == ""

    def test_funding_fee_exempt_flag_included(self):
        block = _demo_context_block("Calculate my IRRRL savings")
        assert "funding_fee_exempt" in block


# ---------------------------------------------------------------------------
# Orchestrator.run() — end-to-end (mocked sub-agents)
# ---------------------------------------------------------------------------

def _make_orchestrator_with_mocks(
    advisor_events: tuple = (),
    action_events: tuple = (),
) -> Orchestrator:
    """
    Return an Orchestrator with both sub-agents replaced by async generator mocks
    and _llm_classify patched to use keyword-based routing (no Azure client needed).

    advisor_events and action_events are tuples of event dicts that the
    respective mock agents will yield when run() is called.
    """
    orch = Orchestrator()

    async def _advisor_run(query: str):
        for event in advisor_events:
            yield event

    async def _action_run(query: str, refi_input=None, appt_input=None):
        for event in action_events:
            yield event

    advisor = MagicMock()
    advisor.run = _advisor_run
    action = MagicMock()
    action.run = _action_run

    orch._advisor = advisor
    orch._action = action
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

    async def test_final_response_is_last_event(self):
        orch = _make_orchestrator_with_mocks()
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        assert events[-1]["type"] == "final_response"
        assert "content" in events[-1]

    async def test_complete_event_emitted_before_final_response(self):
        orch = _make_orchestrator_with_mocks()
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        types = [e["type"] for e in events]
        assert "complete" in types
        assert types.index("complete") < types.index("final_response")

    async def test_advisor_source_events_for_eligibility_query(self):
        orch = _make_orchestrator_with_mocks()
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        source_events = [e for e in events if e["type"] == "advisor_source"]
        assert len(source_events) >= 1

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
        # Internal event must not be forwarded to the client.
        assert "_advisor_text" not in types

    async def test_action_events_forwarded(self):
        """Events from action run (except _action_text) appear in output."""
        action_events = (
            {"type": "action_start", "message": "Loan Action Agent activated"},
            {"type": "action_tool_call", "message": "refi_savings_calculator", "inputs": {}},
            {"type": "action_tool_result", "message": "Monthly savings: $142"},
            {"type": "_action_text", "text": "Your savings are $142/month."},
        )
        orch = _make_orchestrator_with_mocks(action_events=action_events)
        events = await collect_events(orch, "How much would I save by refinancing?")
        types = [e["type"] for e in events]
        assert "action_start" in types
        assert "action_tool_call" in types
        assert "action_tool_result" in types
        # Internal event must not be forwarded to the client.
        assert "_action_text" not in types

    async def test_advisor_text_in_final_response(self):
        """Text from _advisor_text is included in final_response content."""
        advisor_events = (
            {"type": "_advisor_text", "text": "You are eligible for IRRRL."},
        )
        orch = _make_orchestrator_with_mocks(advisor_events=advisor_events)
        events = await collect_events(orch, "Am I eligible for an IRRRL?")
        final = next(e for e in events if e["type"] == "final_response")
        assert "You are eligible for IRRRL." in final["content"]

    async def test_action_text_in_final_response(self):
        """Text from _action_text is included in final_response content."""
        action_events = (
            {"type": "_action_text", "text": "Monthly savings: $142."},
        )
        orch = _make_orchestrator_with_mocks(action_events=action_events)
        events = await collect_events(orch, "How much would I save by refinancing?")
        final = next(e for e in events if e["type"] == "final_response")
        assert "Monthly savings: $142." in final["content"]

    async def test_both_texts_combined_in_final_response(self):
        """Both advisor and action texts appear in the final_response content."""
        advisor_events = (
            {"type": "_advisor_text", "text": "You are eligible."},
        )
        action_events = (
            {"type": "_action_text", "text": "Monthly savings: $142."},
        )
        query = (
            "Am I eligible for an IRRRL and can you show me my savings "
            "and schedule a call for Thursday?"
        )
        orch = _make_orchestrator_with_mocks(
            advisor_events=advisor_events, action_events=action_events
        )
        events = await collect_events(orch, query)
        final = next(e for e in events if e["type"] == "final_response")
        assert "You are eligible." in final["content"]
        assert "Monthly savings: $142." in final["content"]

    async def test_handoff_event_emitted_before_action(self):
        """A handoff event is emitted when transitioning advisor → action."""
        advisor_events = (
            {"type": "_advisor_text", "text": "You are eligible."},
        )
        action_events = (
            {"type": "_action_text", "text": "Monthly savings: $142."},
        )
        query = (
            "Am I eligible for an IRRRL and can you show me my savings "
            "and schedule a call for Thursday?"
        )
        orch = _make_orchestrator_with_mocks(
            advisor_events=advisor_events, action_events=action_events
        )
        events = await collect_events(orch, query)
        types = [e["type"] for e in events]
        assert "handoff" in types

    async def test_error_events_from_advisor_forwarded(self):
        """Error events from sub-agents are forwarded to the output."""
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
        orch = self._make_orch_with_responses('{"needs_advisor": true, "needs_action": false}')
        advisor, action = await orch._llm_classify("Am I eligible for an IRRRL?")
        assert advisor is True
        assert action is False

    async def test_action_only_from_llm(self):
        orch = self._make_orch_with_responses('{"needs_advisor": false, "needs_action": true}')
        advisor, action = await orch._llm_classify("Book a call for Thursday")
        assert advisor is False
        assert action is True

    async def test_both_from_llm(self):
        orch = self._make_orch_with_responses('{"needs_advisor": true, "needs_action": true}')
        advisor, action = await orch._llm_classify("Am I eligible and show me savings?")
        assert advisor is True
        assert action is True

    async def test_markdown_fenced_json_parsed(self):
        """LLM sometimes wraps JSON in a code fence — should still parse."""
        orch = self._make_orch_with_responses(
            '```json\n{"needs_advisor": true, "needs_action": true}\n```'
        )
        advisor, action = await orch._llm_classify("Flagship query")
        assert advisor is True
        assert action is True

    async def test_llm_failure_falls_back_to_keywords(self):
        """If the Responses API raises, keyword classification is used as fallback."""
        orch = Orchestrator()
        orch._orchestrator_version = "1"

        openai_client = MagicMock()
        openai_client.responses.create = AsyncMock(side_effect=Exception("quota_exceeded"))
        mock_client = MagicMock()
        mock_client.get_openai_client = MagicMock(return_value=openai_client)
        orch._get_client = lambda: mock_client

        advisor, action = await orch._llm_classify("Am I eligible for an IRRRL?")
        # Fallback keyword match: "eligib" and "irrrl" → advisor=True, action=False
        assert advisor is True
        assert action is False

    async def test_unparseable_response_falls_back_to_keywords(self):
        """If the LLM returns non-JSON, keyword fallback is used."""
        orch = self._make_orch_with_responses("Sure, I'll help with that!")
        advisor, action = await orch._llm_classify("Am I eligible for an IRRRL?")
        assert advisor is True  # keyword fallback

    async def test_no_version_uses_keyword_fallback(self):
        """If _orchestrator_version is not set, skip LLM and use keywords."""
        orch = Orchestrator()
        assert orch._orchestrator_version is None
        advisor, action = await orch._llm_classify("Book a call for Thursday")
        # keyword fallback: "book" and "thursday" → action=True
        assert action is True
