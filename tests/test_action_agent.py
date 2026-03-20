"""
Tests for ActionAgent.

Covers:
  - _format_tool_result output for refi and appointment tools
  - _parse_mcp_events extraction from response.output
  - run() event sequence and error paths
  - initialize() agent creation and reuse
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from azure.core.exceptions import ResourceNotFoundError

from agents.action_agent import ActionAgent
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


async def collect_events(agent: ActionAgent, query: str) -> list[dict]:
    return [e async for e in agent.run(query)]


# ---------------------------------------------------------------------------
# _format_tool_result
# ---------------------------------------------------------------------------

class TestFormatToolResult:
    def setup_method(self):
        self.agent = ActionAgent()

    def test_refi_result_contains_key_metrics(self):
        data = {
            "monthly_savings": 142.50,
            "annual_savings": 1710.0,
            "break_even_months": 29,
            "is_beneficial": True,
        }
        msg = self.agent._format_tool_result("refi_savings_calculator", json.dumps(data))
        assert "Monthly savings" in msg
        assert "Annual savings" in msg
        assert "Break-even" in msg
        assert "29 months" in msg

    def test_refi_result_passes_benefit_test(self):
        data = {"monthly_savings": 142.50, "annual_savings": 1710.0,
                "break_even_months": 29, "is_beneficial": True}
        msg = self.agent._format_tool_result("refi_savings_calculator", json.dumps(data))
        assert "✓ passes" in msg

    def test_refi_result_fails_benefit_test(self):
        data = {"monthly_savings": 50.0, "annual_savings": 600.0,
                "break_even_months": 40, "is_beneficial": False}
        msg = self.agent._format_tool_result("refi_savings_calculator", json.dumps(data))
        assert "✗ fails" in msg

    def test_appointment_result_contains_key_fields(self):
        data = {
            "confirmed_day": "Thursday",
            "calendar_date": "Thu Mar 26, 2026",
            "confirmed_time": "2:00 PM",
            "loan_officer": "Sarah Chen",
            "confirmation_number": "LOAN-84921",
        }
        msg = self.agent._format_tool_result("appointment_scheduler", json.dumps(data))
        assert "Thursday" in msg
        assert "Sarah Chen" in msg
        assert "LOAN-84921" in msg

    def test_unknown_tool_returns_fallback(self):
        msg = self.agent._format_tool_result("unknown_tool", json.dumps({"result": "ok"}))
        # Should not raise; returns something non-empty
        assert msg

    def test_malformed_json_returns_fallback(self):
        msg = self.agent._format_tool_result("refi_savings_calculator", "not-json")
        assert msg  # Should not raise


# ---------------------------------------------------------------------------
# _parse_mcp_events
# ---------------------------------------------------------------------------

class TestParseMcpEvents:
    def setup_method(self):
        self.agent = ActionAgent()

    def _make_response(self, items):
        r = MagicMock()
        r.output = items
        return r

    def test_single_mcp_call_yields_two_events(self):
        item = MagicMock()
        item.type = "mcp_call"
        item.name = "refi_savings_calculator"
        item.input = {"current_rate": 6.8, "new_rate": 6.1, "balance": 320000,
                      "remaining_term": 27, "funding_fee_exempt": True}
        item.output = json.dumps({"monthly_savings": 142.5, "annual_savings": 1710.0,
                                   "break_even_months": 29, "is_beneficial": True})

        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert len(events) == 2
        assert events[0]["type"] == "action_tool_call"
        assert events[1]["type"] == "action_tool_result"

    def test_tool_call_event_carries_name_and_inputs(self):
        item = MagicMock()
        item.type = "mcp_call"
        item.name = "refi_savings_calculator"
        item.input = {"current_rate": 6.8}
        item.output = "{}"

        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert events[0]["message"] == "refi_savings_calculator"
        assert events[0]["inputs"] == {"current_rate": 6.8}

    def test_two_mcp_calls_yield_four_events(self):
        def _item(name):
            i = MagicMock()
            i.type = "mcp_call"
            i.name = name
            i.input = {}
            i.output = "{}"
            return i

        items = [_item("refi_savings_calculator"), _item("appointment_scheduler")]
        events = self.agent._parse_mcp_events(self._make_response(items))
        assert len(events) == 4
        call_names = [e["message"] for e in events if e["type"] == "action_tool_call"]
        assert "refi_savings_calculator" in call_names
        assert "appointment_scheduler" in call_names

    def test_non_mcp_call_items_ignored(self):
        item = MagicMock()
        item.type = "message"
        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert events == []

    def test_empty_output_returns_empty_list(self):
        r = MagicMock()
        r.output = []
        events = self.agent._parse_mcp_events(r)
        assert events == []

    def test_json_string_input_parsed_to_dict(self):
        item = MagicMock()
        item.type = "mcp_call"
        item.name = "refi_savings_calculator"
        item.input = json.dumps({"current_rate": 6.8, "new_rate": 6.1})
        item.output = "{}"

        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert isinstance(events[0]["inputs"], dict)
        assert events[0]["inputs"]["current_rate"] == 6.8


# ---------------------------------------------------------------------------
# run() — event sequence and error paths
# ---------------------------------------------------------------------------

class TestActionAgentRun:
    async def test_first_event_is_action_start(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        assert events[0]["type"] == "action_start"

    async def test_tool_call_event_emitted(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        call_events = [e for e in events if e["type"] == "action_tool_call"]
        assert len(call_events) >= 1
        assert call_events[0]["message"] == "refi_savings_calculator"
        assert "inputs" in call_events[0]

    async def test_tool_result_event_emitted(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        result_events = [e for e in events if e["type"] == "action_tool_result"]
        assert len(result_events) >= 1

    async def test_action_text_event_is_last(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        assert events[-1]["type"] == "_action_text"

    async def test_action_text_contains_response(self):
        response = "Your monthly savings are $142.50. Break-even: 29 months."
        agent, _ = make_agent(response_text=response)
        events = await collect_events(agent, "Calculate my savings")
        text_event = next(e for e in events if e["type"] == "_action_text")
        assert text_event["text"] == response

    async def test_event_order(self):
        """action_start → action_tool_call → action_tool_result → _action_text"""
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        types = [e["type"] for e in events]

        assert types[0] == "action_start"
        assert types[-1] == "_action_text"

        call_idx = types.index("action_tool_call")
        result_idx = types.index("action_tool_result")
        text_idx = types.index("_action_text")
        assert call_idx < result_idx < text_idx

    async def test_failed_run_emits_error(self):
        agent, mock_client = make_agent()
        openai_client = mock_client.get_openai_client()
        openai_client.responses.create = AsyncMock(side_effect=Exception("model_error"))

        events = await collect_events(agent, "Calculate savings")
        assert any(e["type"] == "error" for e in events)

    async def test_no_mcp_calls_still_completes(self):
        """If the agent returns no mcp_call items, _action_text is still emitted."""
        agent, mock_client = make_agent()
        openai_client = mock_client.get_openai_client()
        response = MagicMock()
        response.output = []
        response.output_text = "I couldn't process that request."
        openai_client.responses.create = AsyncMock(return_value=response)

        events = await collect_events(agent, "Hello")
        assert events[-1]["type"] == "_action_text"
        assert not any(e["type"] == "action_tool_call" for e in events)

    async def test_no_agent_version_triggers_initialize(self):
        agent, mock_client = make_agent()
        agent._agent_version = None
        agent._create_or_update_connection = lambda: None

        events = await collect_events(agent, "Calculate my savings")
        assert agent._agent_version == "1"
        assert any(e["type"] == "_action_text" for e in events)


# ---------------------------------------------------------------------------
# initialize() — agent creation and reuse
# ---------------------------------------------------------------------------

class TestActionAgentInitialize:
    async def test_creates_agent_when_none_exists(self):
        agent = ActionAgent()
        mock_client = make_action_mock_client()
        agent._get_client = lambda: mock_client
        agent._create_or_update_connection = lambda: None
        await agent.initialize()
        mock_client.agents.create_version.assert_called_once()
        assert agent._agent_version == "1"

    async def test_create_version_uses_mcp_tool(self):
        from azure.ai.projects.models import MCPTool
        agent = ActionAgent()
        mock_client = make_action_mock_client()
        agent._get_client = lambda: mock_client
        agent._create_or_update_connection = lambda: None
        await agent.initialize()
        call_kwargs = mock_client.agents.create_version.call_args.kwargs
        definition = call_kwargs["definition"]
        assert any(isinstance(t, MCPTool) for t in definition.tools)

    async def test_mcp_tool_references_mcp_endpoint(self, monkeypatch):
        from azure.ai.projects.models import MCPTool
        monkeypatch.setenv("MCP_ENDPOINT", "https://test-mcp.azurewebsites.net/mcp")
        agent = ActionAgent()
        mock_client = make_action_mock_client()
        agent._get_client = lambda: mock_client
        agent._create_or_update_connection = lambda: None
        await agent.initialize()
        call_kwargs = mock_client.agents.create_version.call_args.kwargs
        mcp_tool = next(t for t in call_kwargs["definition"].tools if isinstance(t, MCPTool))
        assert mcp_tool.server_url == "https://test-mcp.azurewebsites.net/mcp"
        assert set(mcp_tool.allowed_tools) == {"refi_savings_calculator", "appointment_scheduler"}
        assert mcp_tool.require_approval == "never"
        assert mcp_tool.project_connection_id == "va-loan-action-test-conn"

    async def test_arm_connection_called_on_initialize(self):
        agent = ActionAgent()
        mock_client = make_action_mock_client()
        agent._get_client = lambda: mock_client
        called = []
        agent._create_or_update_connection = lambda: called.append(True)
        await agent.initialize()
        assert called, "_create_or_update_connection should be called during initialize()"

