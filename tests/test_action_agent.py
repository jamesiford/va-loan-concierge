"""
Tests for ActionAgent.

Covers:
  - _execute_tool_call dispatch and output correctness
  - _build_prompt parameter injection
  - Event formatters (_refi_event_inputs, _appt_event_inputs)
  - run() event sequence and error paths
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.action_agent import ActionAgent
from tools.refi_calculator import RefiCalculatorInput
from tools.appointment_scheduler import AppointmentInput
from tests.conftest import make_action_mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(response_text: str = "Your savings: $142/month.") -> tuple[ActionAgent, MagicMock]:
    agent = ActionAgent()
    mock_client = make_action_mock_client(response_text)
    agent._get_client = lambda: mock_client
    agent._agent_version = "1"  # skip initialize()
    return agent, mock_client


async def collect_events(agent: ActionAgent, query: str, refi=None, appt=None) -> list[dict]:
    return [e async for e in agent.run(query, refi, appt)]


DEMO_REFI = RefiCalculatorInput(
    current_rate=6.8,
    new_rate=6.1,
    balance=320_000,
    remaining_term=27,
    funding_fee_exempt=True,
)

DEMO_APPT = AppointmentInput(
    preferred_day="Thursday",
    preferred_time="2:00 PM",
)


# ---------------------------------------------------------------------------
# _execute_tool_call
# ---------------------------------------------------------------------------

class TestExecuteToolCall:
    def setup_method(self):
        self.agent = ActionAgent()

    def test_refi_calculator_exempt_passes_benefit_test(self):
        args = json.dumps({
            "current_rate": 6.8,
            "new_rate": 6.1,
            "balance": 320_000,
            "remaining_term": 27,
            "funding_fee_exempt": True,
        })
        msg, output_json = self.agent._execute_tool_call("refi_savings_calculator", args)
        result = json.loads(output_json)

        assert result["monthly_savings"] > 0
        assert result["is_beneficial"] is True
        assert result["break_even_months"] <= 36
        assert "passes" in msg.lower() or "✓" in msg

    def test_refi_calculator_non_exempt_higher_closing_costs(self):
        exempt_args = json.dumps({
            "current_rate": 6.8, "new_rate": 6.1,
            "balance": 320_000, "remaining_term": 27,
            "funding_fee_exempt": True,
        })
        non_exempt_args = json.dumps({
            "current_rate": 6.8, "new_rate": 6.1,
            "balance": 320_000, "remaining_term": 27,
            "funding_fee_exempt": False,
        })
        _, exempt_json = self.agent._execute_tool_call("refi_savings_calculator", exempt_args)
        _, non_exempt_json = self.agent._execute_tool_call("refi_savings_calculator", non_exempt_args)

        exempt_result = json.loads(exempt_json)
        non_exempt_result = json.loads(non_exempt_json)

        assert non_exempt_result["closing_costs"] > exempt_result["closing_costs"]
        assert non_exempt_result["break_even_months"] > exempt_result["break_even_months"]

    def test_appointment_scheduler_returns_confirmation(self):
        args = json.dumps({
            "preferred_day": "Thursday",
            "preferred_time": "2:00 PM",
        })
        msg, output_json = self.agent._execute_tool_call("appointment_scheduler", args)
        result = json.loads(output_json)

        assert "Thursday" in result["confirmed_day"]
        assert result["confirmation_number"].startswith("LOAN-")
        assert "LOAN-" in msg

    def test_appointment_scheduler_normalizes_day(self):
        args = json.dumps({
            "preferred_day": "thurs",
            "preferred_time": "afternoon",
        })
        _, output_json = self.agent._execute_tool_call("appointment_scheduler", args)
        result = json.loads(output_json)
        assert result["confirmed_day"] == "Thursday"

    def test_unknown_tool_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown tool"):
            self.agent._execute_tool_call("nonexistent_tool", "{}")

    def test_refi_result_message_contains_key_metrics(self):
        args = json.dumps({
            "current_rate": 6.8, "new_rate": 6.1,
            "balance": 320_000, "remaining_term": 27,
            "funding_fee_exempt": True,
        })
        msg, _ = self.agent._execute_tool_call("refi_savings_calculator", args)
        assert "Monthly savings" in msg
        assert "Break-even" in msg
        assert "Annual savings" in msg


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def setup_method(self):
        self.agent = ActionAgent()

    def test_no_inputs_returns_query_only(self):
        result = self.agent._build_prompt("How much would I save?", None, None)
        assert result == "How much would I save?"

    def test_refi_input_includes_rates(self):
        result = self.agent._build_prompt("Calculate savings", DEMO_REFI, None)
        assert "6.8" in result
        assert "6.1" in result
        assert str(DEMO_REFI.balance) in result

    def test_appt_input_includes_day(self):
        result = self.agent._build_prompt("Book a call", None, DEMO_APPT)
        assert "Thursday" in result
        assert "2:00 PM" in result

    def test_both_inputs_included(self):
        result = self.agent._build_prompt("Refinance and book", DEMO_REFI, DEMO_APPT)
        assert "6.8" in result
        assert "Thursday" in result

    def test_funding_fee_exempt_flag_present(self):
        result = self.agent._build_prompt("Save money", DEMO_REFI, None)
        assert "funding_fee_exempt" in result


# ---------------------------------------------------------------------------
# Event formatters
# ---------------------------------------------------------------------------

class TestEventFormatters:
    def setup_method(self):
        self.agent = ActionAgent()
        # Get a real result to format.
        args = json.dumps({
            "current_rate": 6.8, "new_rate": 6.1,
            "balance": 320_000, "remaining_term": 27,
            "funding_fee_exempt": True,
        })
        _, self.refi_json = self.agent._execute_tool_call("refi_savings_calculator", args)
        self.refi_result = json.loads(self.refi_json)

    def test_refi_event_inputs_structure(self):
        inputs = self.agent._refi_event_inputs(DEMO_REFI)
        assert "current_rate" in inputs
        assert "new_rate" in inputs
        assert "balance" in inputs
        assert "remaining_term" in inputs
        assert "funding_fee_exempt" in inputs
        assert inputs["current_rate"] == 6.8

    def test_appt_event_inputs_structure(self):
        inputs = self.agent._appt_event_inputs(DEMO_APPT)
        assert "preferred_day" in inputs
        assert "preferred_time" in inputs
        assert inputs["preferred_day"] == "Thursday"


# ---------------------------------------------------------------------------
# run() — event sequence and error paths
# ---------------------------------------------------------------------------

class TestActionAgentRun:
    async def test_first_event_is_action_start(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings", DEMO_REFI)
        assert events[0]["type"] == "action_start"

    async def test_tool_call_event_emitted(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings", DEMO_REFI)
        call_events = [e for e in events if e["type"] == "action_tool_call"]
        assert len(call_events) >= 1
        assert call_events[0]["message"] == "refi_savings_calculator"
        assert "inputs" in call_events[0]

    async def test_tool_result_event_emitted(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings", DEMO_REFI)
        result_events = [e for e in events if e["type"] == "action_tool_result"]
        assert len(result_events) >= 1

    async def test_action_text_event_is_last(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings", DEMO_REFI)
        assert events[-1]["type"] == "_action_text"

    async def test_event_order(self):
        """action_start → action_tool_call → action_tool_result → _action_text"""
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings", DEMO_REFI)
        types = [e["type"] for e in events]

        assert types[0] == "action_start"
        assert types[-1] == "_action_text"

        call_idx = types.index("action_tool_call")
        result_idx = types.index("action_tool_result")
        text_idx = types.index("_action_text")
        assert call_idx < result_idx < text_idx

    async def test_no_inputs_emits_error(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Tell me something", None, None)
        assert any(e["type"] == "error" for e in events)
        # Should not emit action_start before the error.
        assert not any(e["type"] == "action_tool_call" for e in events)

    async def test_failed_run_emits_error(self):
        """If the Responses API raises, an error event should be yielded."""
        agent, mock_client = make_agent()
        openai_client = mock_client.get_openai_client()
        openai_client.responses.create = AsyncMock(side_effect=Exception("model_error"))

        events = await collect_events(agent, "Calculate savings", DEMO_REFI)
        assert any(e["type"] == "error" for e in events)

    async def test_action_text_contains_response(self):
        response = "Your monthly savings are $142.00. Break-even: 29 months."
        agent, _ = make_agent(response_text=response)
        events = await collect_events(agent, "Calculate savings", DEMO_REFI)
        text_event = next(e for e in events if e["type"] == "_action_text")
        assert text_event["text"] == response

    async def test_appointment_tool_call_emitted(self):
        """When an appointment is requested, appointment_scheduler tool call is emitted."""
        agent, mock_client = make_agent()
        openai_client = mock_client.get_openai_client()

        # Override Responses API to return an appointment_scheduler function_call.
        tc = MagicMock()
        tc.type = "function_call"
        tc.name = "appointment_scheduler"
        tc.arguments = json.dumps({
            "preferred_day": "Thursday",
            "preferred_time": "2:00 PM",
        })
        tc.call_id = "call-appt"

        response1 = MagicMock()
        response1.output = [tc]
        response1.output_text = None
        response1.id = "resp-appt-1"

        response2 = MagicMock()
        response2.output = []
        response2.output_text = "Appointment confirmed for Thursday."

        openai_client.responses.create = AsyncMock(side_effect=[response1, response2])

        events = await collect_events(agent, "Book a call for Thursday", None, DEMO_APPT)
        call_events = [e for e in events if e["type"] == "action_tool_call"]
        assert any(e["message"] == "appointment_scheduler" for e in call_events)
