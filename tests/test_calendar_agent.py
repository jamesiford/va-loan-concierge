"""
Tests for CalendarAgent.

Covers:
  - _format_tool_result output for createEvent and findMeetingTimes
  - _parse_mcp_events extraction from response.output
  - event_was_created helper
  - run() event sequence and error paths
  - initialize() agent creation with Work IQ Calendar MCP tools
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.calendar_agent import CalendarAgent
from tests.conftest import make_calendar_mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(response_text: str = "Calendar event created.") -> tuple[CalendarAgent, MagicMock]:
    agent = CalendarAgent()
    mock_client = make_calendar_mock_client(response_text)
    agent._get_client = lambda: mock_client
    agent._agent_version = "1"
    return agent, mock_client


async def collect_events(agent: CalendarAgent, query: str) -> list[dict]:
    return [e async for e in agent.run(query)]


# ---------------------------------------------------------------------------
# _format_tool_result
# ---------------------------------------------------------------------------

class TestFormatToolResult:
    def setup_method(self):
        self.agent = CalendarAgent()

    def test_create_event_result_with_event_id(self):
        data = {"status": "created", "eventId": "abc123"}
        msg = self.agent._format_tool_result(
            "CreateEvent", json.dumps(data)
        )
        assert "abc123" in msg

    def test_create_event_result_without_event_id(self):
        data = {"status": "created"}
        msg = self.agent._format_tool_result(
            "CreateEvent", json.dumps(data)
        )
        assert "Calendar event created" in msg

    def test_unknown_tool_returns_fallback(self):
        msg = self.agent._format_tool_result("unknown_tool", json.dumps({"ok": True}))
        assert msg


# ---------------------------------------------------------------------------
# _parse_mcp_events
# ---------------------------------------------------------------------------

class TestParseMcpEvents:
    def setup_method(self):
        self.agent = CalendarAgent()

    def _make_response(self, items):
        r = MagicMock()
        r.output = items
        return r

    def test_mcp_call_yields_calendar_events(self):
        item = MagicMock()
        item.type = "mcp_call"
        item.name = "CreateEvent"
        item.input = {"subject": "IRRRL review", "start": "2026-03-26T14:00:00"}
        item.output = json.dumps({"status": "created", "eventId": "abc123"})

        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert len(events) == 2
        assert events[0]["type"] == "calendar_tool_call"
        assert events[1]["type"] == "calendar_tool_result"

    def test_non_mcp_call_items_ignored(self):
        item = MagicMock()
        item.type = "message"
        events = self.agent._parse_mcp_events(self._make_response([item]))
        assert events == []


# ---------------------------------------------------------------------------
# run() — event sequence and error paths
# ---------------------------------------------------------------------------

class TestCalendarAgentRun:
    async def test_first_event_is_calendar_start(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Create a calendar event")
        assert events[0]["type"] == "calendar_start"

    async def test_tool_call_event_emitted(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Create a calendar event")
        call_events = [e for e in events if e["type"] == "calendar_tool_call"]
        assert len(call_events) >= 1

    async def test_calendar_text_event_is_last(self):
        agent, _ = make_agent()
        events = await collect_events(agent, "Create a calendar event")
        assert events[-1]["type"] == "_calendar_text"

    async def test_last_response_stored(self):
        agent, _ = make_agent()
        await collect_events(agent, "Create a calendar event")
        assert agent.last_response is not None

    async def test_failed_run_emits_error(self):
        agent, mock_client = make_agent()
        openai_client = mock_client.get_openai_client()
        openai_client.responses.create = AsyncMock(side_effect=Exception("calendar_error"))

        events = await collect_events(agent, "Create a calendar event")
        assert any(e["type"] == "error" for e in events)


# ---------------------------------------------------------------------------
# initialize() — agent creation with Work IQ Calendar MCP tools
# ---------------------------------------------------------------------------

class TestCalendarAgentInitialize:
    async def test_creates_agent_version(self):
        agent = CalendarAgent()
        mock_client = make_calendar_mock_client()
        agent._get_client = lambda: mock_client
        await agent.initialize()
        mock_client.agents.create_version.assert_called_once()
        assert agent._agent_version == "1"

    async def test_agent_has_create_event_tool(self):
        from azure.ai.projects.models import MCPTool
        agent = CalendarAgent()
        mock_client = make_calendar_mock_client()
        agent._get_client = lambda: mock_client
        await agent.initialize()
        call_kwargs = mock_client.agents.create_version.call_args.kwargs
        definition = call_kwargs["definition"]
        mcp_tools = [t for t in definition.tools if isinstance(t, MCPTool)]
        assert len(mcp_tools) == 1
        allowed = mcp_tools[0].allowed_tools
        assert "CreateEvent" in allowed
        assert "mcp_CalendarTools_graph_findMeetingTimes" not in allowed

    async def test_agent_name_ends_with_mcp(self):
        from agents.calendar_agent import _AGENT_NAME
        assert _AGENT_NAME.endswith("-mcp")
