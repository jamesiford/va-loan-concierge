"""
Tests for AdvisorAgent.

Covers:
  - Knowledge file loading
  - Source relevance scoring (_relevant_sources)
  - run() event sequence and content
  - initialize() agent creation and reuse
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from azure.core.exceptions import ResourceNotFoundError

from agents.advisor_agent import AdvisorAgent, KNOWLEDGE_SOURCES, KNOWLEDGE_DIR
from tests.conftest import AsyncList, make_advisor_mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent_with_mock_client(
    response_text: str = "Eligible. [Source: VA Guidelines]",
) -> tuple[AdvisorAgent, MagicMock, MagicMock]:
    """
    Return an AdvisorAgent with both internal clients replaced by mocks.

    Returns (agent, project_client, agents_client).
    """
    agent = AdvisorAgent()
    project_client, agents_client = make_advisor_mock_client(response_text)
    agent._get_project_client = lambda: project_client
    agent._get_agents_client = lambda: agents_client
    return agent, project_client, agents_client


async def collect_events(agent: AdvisorAgent, query: str) -> list[dict]:
    return [event async for event in agent.run(query)]


# ---------------------------------------------------------------------------
# Knowledge loading
# ---------------------------------------------------------------------------

class TestKnowledgeLoading:
    def test_all_knowledge_sources_loaded(self):
        agent = AdvisorAgent()
        for source in KNOWLEDGE_SOURCES:
            assert source["id"] in agent._knowledge

    def test_knowledge_content_nonempty(self):
        agent = AdvisorAgent()
        for source in KNOWLEDGE_SOURCES:
            content = agent._knowledge[source["id"]]
            assert isinstance(content, str)
            assert len(content) > 50, f"Expected substantive content in {source['filename']}"

    def test_knowledge_source_count(self):
        assert len(KNOWLEDGE_SOURCES) == 3
        ids = [s["id"] for s in KNOWLEDGE_SOURCES]
        assert "va_guidelines" in ids
        assert "lender_products" in ids
        assert "loan_process_faq" in ids

    def test_knowledge_files_exist_on_disk(self):
        for source in KNOWLEDGE_SOURCES:
            path = KNOWLEDGE_DIR / source["filename"]
            assert path.exists(), f"Missing knowledge file: {source['filename']}"


# ---------------------------------------------------------------------------
# Source relevance scoring
# ---------------------------------------------------------------------------

class TestRelevantSources:
    def setup_method(self):
        self.agent = AdvisorAgent()

    def _ids(self, query: str) -> list[str]:
        return [s["id"] for s in self.agent._relevant_sources(query)]

    def test_va_guidelines_always_included(self):
        # Even an unrelated query should pull in va_guidelines as the baseline.
        assert "va_guidelines" in self._ids("what is the weather today")

    def test_irrrl_eligibility_query(self):
        ids = self._ids("Am I eligible for an IRRRL?")
        assert "va_guidelines" in ids

    def test_lender_products_keyword_match(self):
        ids = self._ids("What are the available mortgage rates and loan officer options?")
        assert "lender_products" in ids

    def test_faq_second_time_keyword(self):
        ids = self._ids("Can I use my VA loan a second time?")
        assert "loan_process_faq" in ids

    def test_faq_process_keyword(self):
        ids = self._ids("What is the loan process step by step?")
        assert "loan_process_faq" in ids

    def test_mixed_query_includes_multiple_sources(self):
        query = "Am I eligible for an IRRRL and what loan officers do you have?"
        ids = self._ids(query)
        assert "va_guidelines" in ids
        assert "lender_products" in ids

    def test_returns_list_of_source_dicts(self):
        sources = self.agent._relevant_sources("VA loan eligibility")
        assert isinstance(sources, list)
        assert len(sources) >= 1
        for s in sources:
            assert "id" in s
            assert "filename" in s
            assert "label" in s


# ---------------------------------------------------------------------------
# run() — event sequence
# ---------------------------------------------------------------------------

class TestAdvisorAgentRun:
    async def test_first_event_is_advisor_start(self):
        agent, project_client, _ = make_agent_with_mock_client()
        agent._agent_version = "1"  # skip initialize()
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        assert events[0]["type"] == "advisor_start"

    async def test_advisor_source_events_emitted(self):
        agent, project_client, _ = make_agent_with_mock_client()
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        source_events = [e for e in events if e["type"] == "advisor_source"]
        assert len(source_events) >= 1
        for e in source_events:
            assert "message" in e
            assert e["message"].startswith("Querying:")

    async def test_advisor_result_event_emitted(self):
        agent, project_client, _ = make_agent_with_mock_client()
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        types = [e["type"] for e in events]
        assert "advisor_result" in types

    async def test_advisor_text_event_emitted_last(self):
        text = "You are eligible. [Source: VA Guidelines]"
        agent, project_client, _ = make_agent_with_mock_client(response_text=text)
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        assert events[-1]["type"] == "_advisor_text"
        assert events[-1]["text"] == text

    async def test_event_order(self):
        """advisor_start → advisor_source(s) → advisor_result → _advisor_text"""
        agent, project_client, _ = make_agent_with_mock_client()
        agent._agent_version = "1"
        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        types = [e["type"] for e in events]

        assert types[0] == "advisor_start"
        assert "_advisor_text" == types[-1]
        assert "advisor_result" in types
        # All source events come before the result.
        last_source_idx = max((i for i, t in enumerate(types) if t == "advisor_source"), default=-1)
        result_idx = types.index("advisor_result")
        assert last_source_idx < result_idx

    async def test_failed_run_emits_error(self):
        agent, project_client, _ = make_agent_with_mock_client()
        agent._agent_version = "1"

        # Make Responses API raise.
        openai_client = project_client.get_openai_client()
        openai_client.responses.create = AsyncMock(side_effect=Exception("model_error"))

        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1

    async def test_no_agent_version_triggers_initialize(self):
        """run() should call initialize() if _agent_version is not set."""
        agent, project_client, agents_client = make_agent_with_mock_client()
        assert agent._agent_version is None

        events = await collect_events(agent, "Am I eligible for an IRRRL?")
        # initialize() should have been called, setting _agent_version.
        assert agent._agent_version == "1"
        # And the run should still complete.
        assert any(e["type"] == "_advisor_text" for e in events)


# ---------------------------------------------------------------------------
# initialize() — agent and vector store creation / reuse
# ---------------------------------------------------------------------------

class TestAdvisorAgentInitialize:
    async def test_creates_agent_when_none_exists(self):
        agent, project_client, agents_client = make_agent_with_mock_client()
        await agent.initialize()
        project_client.agents.create_version.assert_called_once()
        assert agent._agent_version == "1"

    async def test_creates_vector_store_when_none_exists(self):
        agent, project_client, agents_client = make_agent_with_mock_client()
        await agent.initialize()
        agents_client.vector_stores.create_and_poll.assert_called_once()

    async def test_reuses_existing_agent(self):
        agent, project_client, agents_client = make_agent_with_mock_client()

        # Return an existing agent from agents.get().
        existing = MagicMock()
        existing.versions.latest.version = "existing-version-99"
        project_client.agents.get = AsyncMock(return_value=existing)

        await agent.initialize()

        # Should not create a new agent version.
        project_client.agents.create_version.assert_not_called()
        assert agent._agent_version == "existing-version-99"

    async def test_reuses_existing_vector_store(self):
        agent, project_client, agents_client = make_agent_with_mock_client()

        existing_vs = MagicMock()
        existing_vs.id = "existing-vs-999"
        existing_vs.name = "VA Knowledge Base"
        agents_client.vector_stores.list.return_value = AsyncList([existing_vs])

        await agent.initialize()

        agents_client.vector_stores.create_and_poll.assert_not_called()
        assert agent._vector_store_id == "existing-vs-999"
