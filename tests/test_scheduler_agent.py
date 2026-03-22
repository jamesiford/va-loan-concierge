"""
Tests for SchedulerAgent.

Covers:
  - _format_tool_result output for appointment scheduler
  - _parse_mcp_events extraction from response.output
  - run() event sequence and error paths
  - initialize() agent creation with one MCP tool
  - extract_appointment_result helper
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from azure.core.exceptions import ResourceNotFoundError

from agents.scheduler_agent import SchedulerAgent
from tests.conftest import make_scheduler_mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(response_text: str = "Your appointment is confirmed.") -> tuple[SchedulerAgent, MagicMock]:
    agent = SchedulerAgent()
    mock_client = make_scheduler_mock_client(response_text)
    agent._get_client = lambda: mock_client
    agent._agent_version = "1"
    return agent, mock_client


async def collect_events(agent: SchedulerAgent, query: str) -> list[dict]:
    return [e async for e in agent.run(query)]


# ---------------------------------------------------------------------------
# _format_tool_result
# ---------------------------------------------------------------------------

class TestFormatToolResult:
    def setup_method(self):
        self.agent = SchedulerAgent()

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
        assert msg

    def test_malformed_json_returns_fallback(self):
        msg = self.agent._format_tool_result("appointment_scheduler", "not-json")
        assert msg


# ---------------------------------------------------------------------------
# _parse_mcp_events
# ---------------------------------------------------------------------------

class TestParseMcpEvents:
    def setup_method(self):
        self.agent = SchedulerAgent()

    def _make_response(self, items):
        r = MagicMock()
        r.output = items
        return r

    def test_single_mcp_call_yields_two_events(self):
        item = MagicMock()
        item.type = "mcp_call"
        item.name = "appointment_scheduler"
        item.input = {"preferred_day": "Thursday", "preferred_time": "2:00 PM"}
        item.output = json.dumps({
            "confirmed_day": "Thursday",
            "calendar_date": "Thu Mar 26, 2026",
            "confirmed_time": "2:00 PM",
            "loan_officer": "Sarah Chen",
            "confirmation_number": "LOAN-84921",
        })

        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert len(events) == 2
        assert events[0]["type"] == "scheduler_tool_call"
        assert events[1]["type"] == "scheduler_tool_result"

    def test_non_mcp_call_items_ignored(self):
        item = MagicMock()
        item.type = "message"
        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert events == []


# ---------------------------------------------------------------------------
# extract_appointment_result
# ---------------------------------------------------------------------------

class TestExtractAppointmentResult:
    def setup_method(self):
        self.agent = SchedulerAgent()

    def test_extracts_appointment_json(self):
        item = MagicMock()
        item.type = "mcp_call"
        item.name = "appointment_scheduler"
        item.output = json.dumps({"confirmed_day": "Thursday"})

        response = MagicMock()
        response.output = [item]

        result = self.agent.extract_appointment_result(response)
        assert result is not None
        assert "Thursday" in result

    def test_returns_none_when_no_appointment_call(self):
        item = MagicMock()
        item.type = "message"

        response = MagicMock()
        response.output = [item]

        assert self.agent.extract_appointment_result(response) is None


# ---------------------------------------------------------------------------
# run() — event sequence and error paths
# ---------------------------------------------------------------------------

class TestSchedulerAgentRun:
    async def test_first_event_is_scheduler_start(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Book a call for Thursday")
        assert events[0]["type"] == "scheduler_start"

    async def test_tool_call_event_emitted(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Book a call for Thursday")
        call_events = [e for e in events if e["type"] == "scheduler_tool_call"]
        assert len(call_events) >= 1
        assert call_events[0]["message"] == "appointment_scheduler"

    async def test_scheduler_text_event_is_last(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Book a call for Thursday")
        assert events[-1]["type"] == "_scheduler_text"

    async def test_event_order(self):
        """scheduler_start → scheduler_tool_call → scheduler_tool_result → _scheduler_text"""
        agent, _ = make_agent()
        events = await collect_events(agent, "Book a call for Thursday")
        types = [e["type"] for e in events]

        assert types[0] == "scheduler_start"
        assert types[-1] == "_scheduler_text"

        call_idx = types.index("scheduler_tool_call")
        result_idx = types.index("scheduler_tool_result")
        text_idx = types.index("_scheduler_text")
        assert call_idx < result_idx < text_idx

    async def test_last_response_stored(self):
        agent, _ = make_agent()
        await collect_events(agent, "Book a call for Thursday")
        assert agent.last_response is not None

    async def test_failed_run_emits_error(self):
        agent, mock_client = make_agent()
        openai_client = mock_client.get_openai_client()
        openai_client.responses.create = AsyncMock(side_effect=Exception("model_error"))

        events = await collect_events(agent, "Book a call")
        assert any(e["type"] == "error" for e in events)


# ---------------------------------------------------------------------------
# initialize() — agent creation with one MCP tool
# ---------------------------------------------------------------------------

class TestSchedulerAgentInitialize:
    async def test_creates_agent_version(self):
        agent = SchedulerAgent()
        mock_client = make_scheduler_mock_client()
        agent._get_client = lambda: mock_client
        agent._create_or_update_connection = lambda: None
        await agent.initialize()
        mock_client.agents.create_version.assert_called_once()
        assert agent._agent_version == "1"

    async def test_agent_has_appointment_scheduler_tool(self):
        from azure.ai.projects.models import MCPTool
        agent = SchedulerAgent()
        mock_client = make_scheduler_mock_client()
        agent._get_client = lambda: mock_client
        agent._create_or_update_connection = lambda: None
        await agent.initialize()
        call_kwargs = mock_client.agents.create_version.call_args.kwargs
        definition = call_kwargs["definition"]
        mcp_tools = [t for t in definition.tools if isinstance(t, MCPTool)]
        assert len(mcp_tools) == 1
        assert mcp_tools[0].allowed_tools == ["appointment_scheduler"]
