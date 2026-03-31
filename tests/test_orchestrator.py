"""
Tests for the Orchestrator.

Covers:
  - _classify_hint routing logic (4-way: advisor/calculator/scheduler/newsletter)
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
    async def _stub(query: str) -> tuple[bool, bool, bool, bool, str]:
        return _classify_hint(query)
    orch._llm_classify = _stub


# ---------------------------------------------------------------------------
# _classify_hint
# ---------------------------------------------------------------------------

class TestClassifyHint:
    def test_irrrl_eligibility_query_is_advisor_only(self):
        advisor, calculator, scheduler, newsletter, response = _classify_hint("Am I eligible for an IRRRL?")
        assert advisor is True
        assert calculator is False
        assert scheduler is False
        assert newsletter is False
        assert response == ""

    def test_second_time_query_is_advisor_only(self):
        advisor, calculator, scheduler, newsletter, response = _classify_hint("Can I use my VA loan a second time?")
        assert advisor is True
        assert calculator is False
        assert scheduler is False
        assert newsletter is False
        assert response == ""

    def test_schedule_query_is_scheduler(self):
        advisor, calculator, scheduler, newsletter, response = _classify_hint("Book a call for Thursday")
        assert scheduler is True

    def test_calculation_query_is_calculator(self):
        advisor, calculator, scheduler, newsletter, response = _classify_hint("How much would I save by refinancing?")
        assert calculator is True

    def test_flagship_mixed_query_triggers_all(self):
        query = (
            "I'm thinking about refinancing my VA loan. Am I eligible for an IRRRL, "
            "and can you show me what I'd save and schedule a call for Thursday?"
        )
        advisor, calculator, scheduler, newsletter, response = _classify_hint(query)
        assert advisor is True
        assert calculator is True
        assert scheduler is True
        assert newsletter is False
        assert response == ""

    def test_general_query_returns_capabilities(self):
        advisor, calculator, scheduler, newsletter, response = _classify_hint("Hello there")
        assert advisor is False
        assert calculator is False
        assert scheduler is False
        assert newsletter is False
        assert "VA Loan Concierge" in response
        assert len(response) > 0

    def test_newsletter_query_triggers_newsletter(self):
        advisor, calculator, scheduler, newsletter, response = _classify_hint("Send me the weekly digest")
        assert newsletter is True
        assert response == ""

    def test_route_label_all(self):
        assert _route_label(True, True, True, False) == "Advisor Agent + Calculator Agent + Scheduler Agent"

    def test_route_label_advisor_calculator(self):
        assert _route_label(True, True, False, False) == "Advisor Agent + Calculator Agent"

    def test_route_label_advisor_only(self):
        assert _route_label(True, False, False, False) == "Advisor Agent"

    def test_route_label_scheduler_only(self):
        assert _route_label(False, False, True, False) == "Scheduler Agent"

    def test_route_label_calculator_scheduler(self):
        assert _route_label(False, True, True, False) == "Calculator Agent + Scheduler Agent"

    def test_route_label_general(self):
        assert _route_label(False, False, False, False) == "Concierge (general)"

    def test_route_label_newsletter_only(self):
        assert _route_label(False, False, False, True) == "Newsletter Agent"


# ---------------------------------------------------------------------------
# _demo_context_block
# ---------------------------------------------------------------------------

class TestDemoContextBlock:
    def test_calculator_target_includes_loan_params(self):
        block, notices = _demo_context_block("I want to refinance my VA loan", profile_id="marcus", target_agent="calculator")
        assert "6.8" in block
        assert "6.1" in block
        assert "320000" in block
        assert notices == []  # marcus has all fields — no fallbacks

    def test_scheduler_target_includes_appointment_params(self):
        block, notices = _demo_context_block("Book a call for Thursday", profile_id="marcus", target_agent="scheduler")
        assert "appointment_scheduler" in block

    def test_calculator_target_excludes_scheduling(self):
        block, notices = _demo_context_block("Book a call for Thursday", profile_id="marcus", target_agent="calculator")
        assert block == ""

    def test_scheduler_target_excludes_loan_params(self):
        block, notices = _demo_context_block("I want to refinance my VA loan", profile_id="marcus", target_agent="scheduler")
        assert block == ""

    def test_unrelated_query_returns_empty(self):
        block, notices = _demo_context_block("What is the VA loan funding fee waiver?", profile_id="marcus", target_agent="calculator")
        assert block == ""

    def test_funding_fee_exempt_flag_included(self):
        block, notices = _demo_context_block("Calculate my IRRRL savings", profile_id="marcus", target_agent="calculator")
        assert "funding_fee_exempt" in block

    def test_fallback_notices_when_fields_missing(self):
        """When profile fields are missing, notices list the defaults used."""
        block, notices = _demo_context_block("Calculate my IRRRL savings", profile_id="marcus", target_agent="calculator")
        # marcus has all fields — no notices
        assert notices == []

    def test_fallback_notices_for_incomplete_profile(self):
        """A profile with current_rate but missing other fields triggers notices."""
        from unittest.mock import patch
        incomplete = {"current_rate": 7.0}  # missing balance, new_rate, remaining_term, funding_fee_exempt
        with patch.dict("profiles.DEMO_PROFILES", {"incomplete": incomplete}):
            block, notices = _demo_context_block("Calculate my savings", profile_id="incomplete", target_agent="calculator")
            assert len(notices) == 4
            assert any("balance" in n for n in notices)
            assert any("rate" in n.lower() for n in notices)
            assert any("term" in n.lower() for n in notices)
            assert any("exemption" in n.lower() for n in notices)


# ---------------------------------------------------------------------------
# Orchestrator.run() — end-to-end (mocked sub-agents)
# ---------------------------------------------------------------------------

def _make_orchestrator_with_mocks(
    advisor_events: tuple = (),
    calculator_events: tuple = (),
    scheduler_events: tuple = (),
    calendar_events: tuple = (),
    newsletter_events: tuple = (),
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

    async def _newsletter_run(**kwargs):
        for event in newsletter_events:
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
    newsletter = MagicMock()
    newsletter.run = _newsletter_run

    orch._advisor = advisor
    orch._calculator = calculator
    orch._scheduler = scheduler
    orch._calendar = calendar
    orch._newsletter = newsletter
    orch._orchestrator_version = "1"  # skip initialize()
    _patch_llm_classify(orch)         # keyword stub — no Azure client

    return orch


async def collect_events(orch: Orchestrator, query: str, profile_id: str | None = None) -> list[dict]:
    return [e async for e in orch.run(query, profile_id=profile_id)]


class TestOrchestratorRun:
    async def test_general_query_returns_capabilities_without_sub_agents(self):
        """A meta query like 'Hello' should get a direct response, no sub-agents."""
        orch = _make_orchestrator_with_mocks()
        events = await collect_events(orch, "Hello, what can you do?")
        types = [e["type"] for e in events]
        # Should have orchestrator_start, orchestrator_route, partial_response, complete
        assert "orchestrator_start" in types
        assert "orchestrator_route" in types
        assert "partial_response" in types
        assert "complete" in types
        # Should NOT route to any sub-agents
        assert "advisor_start" not in types
        assert "calculator_start" not in types
        assert "scheduler_start" not in types
        assert "plan" not in types
        # The partial_response should be from the orchestrator, not a sub-agent
        partial = next(e for e in events if e["type"] == "partial_response")
        assert partial["agent"] == "orchestrator"
        assert "VA Loan Concierge" in partial["content"]

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
        events = await collect_events(orch, "How much would I save by refinancing?", profile_id="marcus")
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
        events = await collect_events(orch, "Book a call for Thursday", profile_id="marcus")
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
        events = await collect_events(orch, "How much would I save by refinancing?", profile_id="marcus")
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
        events = await collect_events(orch, query, profile_id="marcus")
        partials = [e for e in events if e["type"] == "partial_response"]
        # 3 agent partials; scheduler ends with await_input (no calendar partial)
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
        events = await collect_events(orch, query, profile_id="marcus")
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
            '{"needs_advisor": true, "needs_calculator": false, "needs_scheduler": false, "needs_newsletter": false}'
        )
        advisor, calculator, scheduler, newsletter, _response = await orch._llm_classify("Am I eligible for an IRRRL?")
        assert advisor is True
        assert calculator is False
        assert scheduler is False
        assert newsletter is False

    async def test_calculator_only_from_llm(self):
        orch = self._make_orch_with_responses(
            '{"needs_advisor": false, "needs_calculator": true, "needs_scheduler": false, "needs_newsletter": false}'
        )
        advisor, calculator, scheduler, newsletter, _response = await orch._llm_classify("Show me my savings")
        assert advisor is False
        assert calculator is True
        assert scheduler is False
        assert newsletter is False

    async def test_scheduler_only_from_llm(self):
        orch = self._make_orch_with_responses(
            '{"needs_advisor": false, "needs_calculator": false, "needs_scheduler": true, "needs_newsletter": false}'
        )
        advisor, calculator, scheduler, newsletter, _response = await orch._llm_classify("Book a call for Thursday")
        assert advisor is False
        assert calculator is False
        assert scheduler is True
        assert newsletter is False

    async def test_newsletter_from_llm(self):
        orch = self._make_orch_with_responses(
            '{"needs_advisor": false, "needs_calculator": false, "needs_scheduler": false, "needs_newsletter": true}'
        )
        advisor, calculator, scheduler, newsletter, _response = await orch._llm_classify("Send me the weekly digest")
        assert advisor is False
        assert calculator is False
        assert scheduler is False
        assert newsletter is True

    async def test_all_from_llm(self):
        orch = self._make_orch_with_responses(
            '{"needs_advisor": true, "needs_calculator": true, "needs_scheduler": true, "needs_newsletter": false}'
        )
        advisor, calculator, scheduler, newsletter, _response = await orch._llm_classify("Flagship query")
        assert advisor is True
        assert calculator is True
        assert scheduler is True

    async def test_markdown_fenced_json_parsed(self):
        orch = self._make_orch_with_responses(
            '```json\n{"needs_advisor": true, "needs_calculator": true, "needs_scheduler": false, "needs_newsletter": false}\n```'
        )
        advisor, calculator, scheduler, newsletter, _response = await orch._llm_classify("Flagship query")
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

        advisor, calculator, scheduler, newsletter, _response = await orch._llm_classify("Am I eligible for an IRRRL?")
        assert advisor is True
        assert calculator is False

    async def test_no_version_uses_keyword_fallback(self):
        orch = Orchestrator()
        assert orch._orchestrator_version is None
        advisor, calculator, scheduler, newsletter, _response = await orch._llm_classify("Book a call for Thursday")
        assert scheduler is True


# ---------------------------------------------------------------------------
# Human-in-the-loop tests
# ---------------------------------------------------------------------------

class TestHumanInTheLoop:
    async def test_no_profile_pauses_before_calculator(self):
        """Without a profile, orchestrator pauses for info before calculator."""
        calculator_events = (
            {"type": "_calculator_text", "text": "Savings: $142."},
        )
        orch = _make_orchestrator_with_mocks(calculator_events=calculator_events)
        # No profile_id → should pause with await_input
        events = await collect_events(orch, "How much would I save by refinancing?")
        types = [e["type"] for e in events]
        assert "await_input" in types
        # Calculator should NOT have run
        assert "calculator_start" not in types
        assert "_calculator_text" not in types

    async def test_profile_skips_hil_pause(self):
        """With a profile, orchestrator goes straight to calculator."""
        calculator_events = (
            {"type": "calculator_start", "message": "Calculator activated"},
            {"type": "_calculator_text", "text": "Savings: $142."},
        )
        orch = _make_orchestrator_with_mocks(calculator_events=calculator_events)
        events = await collect_events(orch, "How much would I save by refinancing?", profile_id="marcus")
        types = [e["type"] for e in events]
        assert "await_input" not in types
        assert "calculator_start" in types

    async def test_scheduler_pauses_for_appointment_confirmation(self):
        """After scheduler runs, orchestrator pauses for appointment confirmation."""
        scheduler_events = (
            {"type": "scheduler_start", "message": "Scheduler activated"},
            {"type": "_scheduler_text", "text": "Appointment confirmed."},
        )
        orch = _make_orchestrator_with_mocks(scheduler_events=scheduler_events)
        # Make the scheduler return appointment data so the HIL check triggers
        orch._scheduler.last_response = MagicMock()
        orch._scheduler.extract_appointment_result = MagicMock(
            return_value='{"date": "Thu Mar 26", "time": "2:00 PM", "ref": "LOAN-84921"}'
        )
        # Use marcus profile to skip the profile-info pause
        events = await collect_events(orch, "Book a call for Thursday", profile_id="marcus")
        types = [e["type"] for e in events]
        assert "await_input" in types
        await_evt = next(e for e in events if e["type"] == "await_input")
        assert await_evt["input_type"] == "appointment_confirmation"
        assert "conversation_id" in await_evt

    async def test_await_input_has_suggestions(self):
        """await_input events include suggestion buttons."""
        calculator_events = (
            {"type": "_calculator_text", "text": "Savings."},
        )
        orch = _make_orchestrator_with_mocks(calculator_events=calculator_events)
        events = await collect_events(orch, "How much would I save?")
        await_evt = next(e for e in events if e["type"] == "await_input")
        assert "suggestions" in await_evt
        assert len(await_evt["suggestions"]) > 0

    async def test_keyword_classify_confirmation(self):
        orch = Orchestrator()
        assert orch._keyword_classify_confirmation("Yes, add to my calendar") == "confirm"
        assert orch._keyword_classify_confirmation("Can we do Friday instead?") == "reschedule"
        assert orch._keyword_classify_confirmation("No thanks") == "decline"
        assert orch._keyword_classify_confirmation("Looks good") == "confirm"

    async def test_scheduler_only_no_profile_skips_hil(self):
        """Scheduler-only flow should NOT pause for loan details even without a profile."""
        scheduler_events = (
            {"type": "scheduler_start", "message": "Scheduler activated"},
            {"type": "_scheduler_text", "text": "Appointment confirmed."},
        )
        orch = _make_orchestrator_with_mocks(scheduler_events=scheduler_events)
        # No profile, scheduler-only query — should NOT get profile_info pause
        events = await collect_events(orch, "Book a call for Thursday")
        types = [e["type"] for e in events]
        # Should NOT pause for profile info
        profile_pauses = [e for e in events if e.get("input_type") == "profile_info"]
        assert len(profile_pauses) == 0
        # Scheduler should have run
        assert "scheduler_start" in types

    async def test_resume_with_user_details_skips_demo_context(self):
        """When user provides loan details via HIL, calculator should NOT get the
        'no existing VA loan' demo context block."""
        from api.conversation_state import get_conversation

        calculator_events = (
            {"type": "calculator_start", "message": "Calculator activated"},
            {"type": "calculator_tool_call", "message": "refi_savings_calculator", "inputs": {}},
            {"type": "_calculator_text", "text": "Savings: $142."},
        )
        orch = _make_orchestrator_with_mocks(calculator_events=calculator_events)
        # First call: no profile → pauses for profile_info
        events = await collect_events(orch, "How much would I save by refinancing?")
        await_evt = next(e for e in events if e["type"] == "await_input")
        conv_id = await_evt["conversation_id"]

        # Verify the state was saved
        state = await get_conversation(conv_id)
        assert state is not None
        assert state.pending_action == "awaiting_profile_info"

        # Resume with user-provided details
        events2 = [e async for e in orch.run(
            "Balance $320,000, current rate 6.8%, new rate 6.1%, 27 years left, fee exempt",
            conversation_id=conv_id,
        )]
        types2 = [e["type"] for e in events2]
        # Calculator should have run this time
        assert "calculator_start" in types2
        # Verify state flag was set
        state2 = await get_conversation(conv_id)
        if state2:
            assert state2.user_provided_details is True

    async def test_calculator_retry_when_tool_not_called(self):
        """If the calculator LLM asks follow-up questions (no tool call),
        the orchestrator should pause for a calculator retry."""
        from api.conversation_state import get_conversation

        # First pass: calculator returns text but NO tool_call → asking questions
        calculator_events_incomplete = (
            {"type": "calculator_start", "message": "Calculator activated"},
            {"type": "_calculator_text", "text": "I need your quoted rate to proceed."},
        )
        # Second pass: calculator calls the tool successfully
        calculator_events_complete = (
            {"type": "calculator_start", "message": "Calculator activated"},
            {"type": "calculator_tool_call", "message": "refi_savings_calculator", "inputs": {}},
            {"type": "_calculator_text", "text": "Savings: $142."},
        )

        orch = _make_orchestrator_with_mocks(
            calculator_events=calculator_events_incomplete,
        )
        # Step 1: no profile → pauses for profile_info
        events = await collect_events(orch, "How much would I save by refinancing?")
        await_evt = next(e for e in events if e["type"] == "await_input")
        conv_id = await_evt["conversation_id"]
        assert await_evt["input_type"] == "profile_info"

        # Step 2: provide PARTIAL details → calculator runs but doesn't call tool
        events2 = [e async for e in orch.run(
            "Balance $400K, current rate 7.1%, 29 years remaining",
            conversation_id=conv_id,
        )]
        types2 = [e["type"] for e in events2]
        # Should show calculator's question then pause for retry
        assert "partial_response" in types2
        retry_events = [e for e in events2 if e.get("input_type") == "calculator_retry"]
        assert len(retry_events) == 1

        # Step 3: provide missing details → swap in complete calculator events
        async def _calc_run_complete(query):
            for event in calculator_events_complete:
                yield event
        orch._calculator.run = _calc_run_complete

        events3 = [e async for e in orch.run(
            "New rate 6.3%, not fee exempt",
            conversation_id=conv_id,
        )]
        types3 = [e["type"] for e in events3]
        assert "calculator_tool_call" in types3
        assert "complete" in types3

    async def test_calculator_retry_skip(self):
        """User can say 'skip' during calculator retry to bypass calculation."""
        from api.conversation_state import get_conversation

        calculator_events_incomplete = (
            {"type": "calculator_start", "message": "Calculator activated"},
            {"type": "_calculator_text", "text": "I need your quoted rate."},
        )
        orch = _make_orchestrator_with_mocks(
            calculator_events=calculator_events_incomplete,
        )
        # Step 1: no profile → pauses for profile_info
        events = await collect_events(orch, "How much would I save by refinancing?")
        conv_id = next(e for e in events if e["type"] == "await_input")["conversation_id"]

        # Step 2: provide partial details → calculator retry pause
        events2 = [e async for e in orch.run(
            "Balance $400K, rate 7.1%",
            conversation_id=conv_id,
        )]
        retry_events = [e for e in events2 if e.get("input_type") == "calculator_retry"]
        assert len(retry_events) == 1
        # Verify skip suggestion is offered
        assert any("skip" in s.lower() for s in retry_events[0]["suggestions"])

        # Step 3: user says "skip" → should complete without re-running calculator
        events3 = [e async for e in orch.run(
            "Skip the calculation",
            conversation_id=conv_id,
        )]
        types3 = [e["type"] for e in events3]
        assert "calculator_note" in types3
        note_msgs = [e["message"] for e in events3 if e["type"] == "calculator_note"]
        assert any("skipped" in m.lower() for m in note_msgs)
        # Should NOT have re-run calculator
        assert "calculator_start" not in types3
        assert "complete" in types3
