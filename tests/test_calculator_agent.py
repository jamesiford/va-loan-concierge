"""
Tests for CalculatorAgent.

Covers:
  - _format_tool_result output for refi calculator
  - _parse_mcp_events extraction from response.output
  - run() event sequence and error paths
  - initialize() agent creation
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from azure.core.exceptions import ResourceNotFoundError

from agents.calculator_agent import CalculatorAgent
from tests.conftest import make_calculator_mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(response_text: str = "Your savings: $142/month.") -> tuple[CalculatorAgent, MagicMock]:
    agent = CalculatorAgent()
    mock_client = make_calculator_mock_client(response_text)
    agent._get_client = lambda: mock_client
    agent._agent_version = "1"  # skip initialize()
    return agent, mock_client


async def collect_events(agent: CalculatorAgent, query: str) -> list[dict]:
    return [e async for e in agent.run(query)]


# ---------------------------------------------------------------------------
# _format_tool_result
# ---------------------------------------------------------------------------

class TestFormatToolResult:
    def setup_method(self):
        self.agent = CalculatorAgent()

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

    def test_unknown_tool_returns_fallback(self):
        msg = self.agent._format_tool_result("unknown_tool", json.dumps({"result": "ok"}))
        assert msg

    def test_malformed_json_returns_fallback(self):
        msg = self.agent._format_tool_result("refi_savings_calculator", "not-json")
        assert msg


# ---------------------------------------------------------------------------
# _parse_mcp_events
# ---------------------------------------------------------------------------

class TestParseMcpEvents:
    def setup_method(self):
        self.agent = CalculatorAgent()

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
        assert events[0]["type"] == "calculator_tool_call"
        assert events[1]["type"] == "calculator_tool_result"

    def test_tool_call_event_carries_name_and_inputs(self):
        item = MagicMock()
        item.type = "mcp_call"
        item.name = "refi_savings_calculator"
        item.input = {"current_rate": 6.8}
        item.output = "{}"

        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert events[0]["message"] == "refi_savings_calculator"
        assert events[0]["inputs"] == {"current_rate": 6.8}

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


# ---------------------------------------------------------------------------
# run() — event sequence and error paths
# ---------------------------------------------------------------------------

class TestCalculatorAgentRun:
    async def test_first_event_is_calculator_start(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        assert events[0]["type"] == "calculator_start"

    async def test_tool_call_event_emitted(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        call_events = [e for e in events if e["type"] == "calculator_tool_call"]
        assert len(call_events) >= 1
        assert call_events[0]["message"] == "refi_savings_calculator"

    async def test_tool_result_event_emitted(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        result_events = [e for e in events if e["type"] == "calculator_tool_result"]
        assert len(result_events) >= 1

    async def test_calculator_text_event_is_last(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        assert events[-1]["type"] == "_calculator_text"

    async def test_event_order(self):
        """calculator_start → calculator_tool_call → calculator_tool_result → _calculator_text"""
        agent, _ = make_agent()
        events = await collect_events(agent, "Calculate my savings")
        types = [e["type"] for e in events]

        assert types[0] == "calculator_start"
        assert types[-1] == "_calculator_text"

        call_idx = types.index("calculator_tool_call")
        result_idx = types.index("calculator_tool_result")
        text_idx = types.index("_calculator_text")
        assert call_idx < result_idx < text_idx

    async def test_failed_run_emits_error(self):
        agent, mock_client = make_agent()
        openai_client = mock_client.get_openai_client()
        openai_client.responses.create = AsyncMock(side_effect=Exception("model_error"))

        events = await collect_events(agent, "Calculate savings")
        assert any(e["type"] == "error" for e in events)


# ---------------------------------------------------------------------------
# initialize() — agent creation
# ---------------------------------------------------------------------------

class TestCalculatorAgentInitialize:
    async def test_creates_agent_when_none_exists(self):
        agent = CalculatorAgent()
        mock_client = make_calculator_mock_client()
        agent._get_client = lambda: mock_client
        agent._create_or_update_connection = lambda: None
        await agent.initialize()
        mock_client.agents.create_version.assert_called_once()
        assert agent._agent_version == "1"

    async def test_create_version_uses_mcp_tool(self):
        from azure.ai.projects.models import MCPTool
        agent = CalculatorAgent()
        mock_client = make_calculator_mock_client()
        agent._get_client = lambda: mock_client
        agent._create_or_update_connection = lambda: None
        await agent.initialize()
        call_kwargs = mock_client.agents.create_version.call_args.kwargs
        definition = call_kwargs["definition"]
        assert any(isinstance(t, MCPTool) for t in definition.tools)

    async def test_mcp_tool_restricted_to_calculator(self, monkeypatch):
        from azure.ai.projects.models import MCPTool
        monkeypatch.setenv("MCP_TOOLS_ENDPOINT", "https://test-mcp.azurewebsites.net/mcp")
        agent = CalculatorAgent()
        mock_client = make_calculator_mock_client()
        agent._get_client = lambda: mock_client
        agent._create_or_update_connection = lambda: None
        await agent.initialize()
        call_kwargs = mock_client.agents.create_version.call_args.kwargs
        mcp_tool = next(t for t in call_kwargs["definition"].tools if isinstance(t, MCPTool))
        assert mcp_tool.allowed_tools == ["refi_savings_calculator"]
        assert mcp_tool.require_approval == "never"
