"""
Tests for AdvisorAgent.

Covers:
  - run() event sequence and content
  - Citation extraction from 【idx†source】 markers and annotation objects
  - initialize() agent creation and reuse; ARM connection provisioning
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from azure.core.exceptions import ResourceNotFoundError

from agents.advisor_agent import AdvisorAgent
from tests.conftest import make_advisor_mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent_with_mock_client(
    response_text: str = "Eligible. 【1:0†va_guidelines】",
) -> tuple[AdvisorAgent, MagicMock]:
    """
    Return an AdvisorAgent with its project client mocked and the ARM
    connection call patched out so tests never hit external services.
    """
    agent = AdvisorAgent()
    project_client = make_advisor_mock_client(response_text)
    agent._get_project_client = lambda: project_client
    # Patch the sync ARM call so it's a no-op in tests.
    agent._create_or_update_connection = lambda: None
    return agent, project_client


async def collect_events(agent: AdvisorAgent, query: str) -> list[dict]:
    return [event async for event in agent.run(query)]


# ---------------------------------------------------------------------------
# run() — event sequence
# ---------------------------------------------------------------------------

class TestAdvisorAgentRun:
    async def test_first_event_is_advisor_start(self):
        agent, _ = make_agent_with_mock_client()
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        assert events[0]["type"] == "advisor_start"

    async def test_advisor_source_event_emitted_for_kb_search(self):
        agent, _ = make_agent_with_mock_client()
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        source_events = [e for e in events if e["type"] == "advisor_source"]
        assert len(source_events) >= 1

    async def test_advisor_result_event_emitted(self):
        agent, _ = make_agent_with_mock_client()
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        assert any(e["type"] == "advisor_result" for e in events)

    async def test_advisor_text_event_is_last(self):
        text = "You are eligible. 【1:0†va_guidelines】"
        agent, _ = make_agent_with_mock_client(response_text=text)
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        assert events[-1]["type"] == "_advisor_text"
        assert events[-1]["text"] == text

    async def test_event_order(self):
        """advisor_start → advisor_source(s) → advisor_result → _advisor_text"""
        agent, _ = make_agent_with_mock_client()
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        types = [e["type"] for e in events]

        assert types[0] == "advisor_start"
        assert types[-1] == "_advisor_text"
        assert "advisor_result" in types
        last_source_idx = max(
            (i for i, t in enumerate(types) if t == "advisor_source"), default=-1
        )
        result_idx = types.index("advisor_result")
        assert last_source_idx < result_idx

    async def test_failed_run_emits_error(self):
        agent, project_client = make_agent_with_mock_client()
        agent._agent_version = "1"
        openai_client = project_client.get_openai_client()
        openai_client.responses.create = AsyncMock(side_effect=Exception("model_error"))

        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        assert any(e["type"] == "error" for e in events)

    async def test_no_agent_version_triggers_initialize(self):
        """run() calls initialize() if _agent_version is not set."""
        agent, _ = make_agent_with_mock_client()
        assert agent._agent_version is None

        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        assert agent._agent_version == "1"
        assert any(e["type"] == "_advisor_text" for e in events)


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------

class TestCitationExtraction:
    def setup_method(self):
        self.agent = AdvisorAgent()

    def test_citation_markers_parsed_from_text(self):
        text = "The IRRRL is available 【1:0†va_guidelines.md】 with no appraisal 【1:1†lender_products.md】."
        citations = self.agent._extract_citations(text)
        assert citations == ["va_guidelines.md", "lender_products.md"]

    def test_duplicate_citations_deduplicated(self):
        text = "See 【1:0†va_guidelines.md】 and also 【2:0†va_guidelines.md】."
        citations = self.agent._extract_citations(text)
        assert citations.count("va_guidelines.md") == 1

    def test_generic_labels_filtered(self):
        text = "See 【1:0†source】 and 【1:1†doc_0】 and 【1:2†va_guidelines.md】."
        citations = self.agent._extract_citations(text)
        assert citations == ["va_guidelines.md"]

    async def test_citation_markers_emitted_as_advisor_source_events(self):
        text = "Eligible 【1:0†va_guidelines】."
        agent, _ = make_agent_with_mock_client(response_text=text)
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        cited_events = [
            e for e in events
            if e["type"] == "advisor_source" and "Cited:" in e.get("message", "")
        ]
        assert len(cited_events) == 1
        assert "va_guidelines" in cited_events[0]["message"]

    async def test_no_citations_still_completes(self):
        agent, project_client = make_agent_with_mock_client(response_text="No answer found.")
        agent._agent_version = "1"
        openai_client = project_client.get_openai_client()
        openai_client.responses.create.return_value = MagicMock(
            output=[], output_text="No answer found."
        )
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        assert any(e["type"] == "advisor_result" for e in events)
        assert any(e["type"] == "_advisor_text" for e in events)


# ---------------------------------------------------------------------------
# initialize() — connection provisioning and agent creation/reuse
# ---------------------------------------------------------------------------

class TestAdvisorAgentInitialize:
    async def test_arm_connection_called_on_initialize(self):
        agent, project_client = make_agent_with_mock_client()
        called = []
        agent._create_or_update_connection = lambda: called.append(True)
        await agent.initialize()
        assert called, "_create_or_update_connection should be called during initialize()"

    async def test_creates_agent_when_none_exists(self):
        agent, project_client = make_agent_with_mock_client()
        await agent.initialize()
        project_client.agents.create_version.assert_called_once()
        assert agent._agent_version == "1"

    async def test_create_version_uses_mcp_tool(self):
        from azure.ai.projects.models import MCPTool
        agent, project_client = make_agent_with_mock_client()
        await agent.initialize()
        call_kwargs = project_client.agents.create_version.call_args.kwargs
        definition = call_kwargs["definition"]
        assert any(isinstance(t, MCPTool) for t in definition.tools)

    async def test_mcp_tool_references_correct_kb(self):
        from azure.ai.projects.models import MCPTool
        agent, project_client = make_agent_with_mock_client()
        await agent.initialize()
        call_kwargs = project_client.agents.create_version.call_args.kwargs
        mcp_tool = next(
            t for t in call_kwargs["definition"].tools if isinstance(t, MCPTool)
        )
        assert "kb-va-loan-test" in mcp_tool.server_url
        assert mcp_tool.allowed_tools == ["knowledge_base_retrieve"]
        assert mcp_tool.require_approval == "never"

