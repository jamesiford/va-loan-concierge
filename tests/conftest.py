"""
Shared test helpers and fixtures.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.core.exceptions import ResourceNotFoundError

# Ensure required env vars exist before any module-level imports trigger them.
os.environ.setdefault("PROJECT_ENDPOINT", "https://test.foundry.azure.com")
os.environ.setdefault("MODEL_DEPLOYMENT_NAME", "gpt-4o-test")


# ---------------------------------------------------------------------------
# Async iterable helper
# ---------------------------------------------------------------------------

class AsyncList:
    """Wraps a plain list as an async iterable for mocking SDK paged responses."""

    def __init__(self, items=()):
        self._items = list(items)

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for item in self._items:
            yield item


# ---------------------------------------------------------------------------
# Mock client factories
# ---------------------------------------------------------------------------

def make_advisor_mock_client(
    response_text: str = "IRRRL eligibility confirmed. [Source: VA Guidelines]",
) -> tuple[MagicMock, MagicMock]:
    """
    Build mock (project_client, agents_client) for AdvisorAgent.

    project_client — AIProjectClient mock (agent registration + Responses API)
    agents_client  — AgentsClient mock (vector store / file operations)

    Default: no existing agents or vector stores → triggers full creation path.
    """
    # ── AIProjectClient mock ───────────────────────────────────────────────
    project_client = MagicMock()

    # agents.get raises ResourceNotFoundError (no existing agent to reuse).
    project_client.agents.get = AsyncMock(
        side_effect=ResourceNotFoundError("not found")
    )

    # create_version returns a version object with .version = "1".
    version_obj = MagicMock()
    version_obj.version = "1"
    project_client.agents.create_version = AsyncMock(return_value=version_obj)

    # Responses API — returns a simple text response (no tool calls).
    openai_client = MagicMock()
    response = MagicMock()
    response.output = []
    response.output_text = response_text
    openai_client.responses.create = AsyncMock(return_value=response)
    project_client.get_openai_client = MagicMock(return_value=openai_client)

    # ── AgentsClient mock ──────────────────────────────────────────────────
    agents_client = MagicMock()

    # Listing returns empty (no existing vector stores).
    agents_client.vector_stores.list.return_value = AsyncList()

    # File upload.
    uploaded_file = MagicMock()
    uploaded_file.id = "file-001"
    agents_client.files.upload_and_poll = AsyncMock(return_value=uploaded_file)

    # Vector store creation.
    vs = MagicMock()
    vs.id = "vs-001"
    vs.name = "VA Knowledge Base"
    agents_client.vector_stores.create_and_poll = AsyncMock(return_value=vs)

    return project_client, agents_client


def make_action_mock_client(
    response_text: str = "Your monthly savings are $142.",
) -> MagicMock:
    """
    Build a mock AIProjectClient for ActionAgent.

    Simulates one requires-action cycle for refi_savings_calculator:
      - First Responses API call returns a function_call item.
      - Second Responses API call (after tool output submission) returns
        the final text response.
    """
    client = MagicMock()

    # Agent registration.
    client.agents.get = AsyncMock(side_effect=ResourceNotFoundError("not found"))
    version_obj = MagicMock()
    version_obj.version = "1"
    client.agents.create_version = AsyncMock(return_value=version_obj)

    # Responses API.
    openai_client = MagicMock()

    # First response: one refi_savings_calculator function_call.
    tc = MagicMock()
    tc.type = "function_call"
    tc.name = "refi_savings_calculator"
    tc.arguments = json.dumps({
        "current_rate": 6.8,
        "new_rate": 6.1,
        "balance": 320000,
        "remaining_term": 27,
        "funding_fee_exempt": True,
    })
    tc.call_id = "call-001"

    response1 = MagicMock()
    response1.output = [tc]
    response1.output_text = None
    response1.id = "resp-001"

    # Second response: no tool calls, final text.
    response2 = MagicMock()
    response2.output = []
    response2.output_text = response_text

    openai_client.responses.create = AsyncMock(side_effect=[response1, response2])
    client.get_openai_client = MagicMock(return_value=openai_client)

    return client


def make_orchestrator_mock_client() -> MagicMock:
    """
    Build a mock AIProjectClient for Orchestrator initialization.

    The Orchestrator's run() delegates to sub-agents (mocked separately in
    tests), so only the agent registration path needs to be mocked here.
    """
    client = MagicMock()

    client.agents.get = AsyncMock(side_effect=ResourceNotFoundError("not found"))
    version_obj = MagicMock()
    version_obj.version = "1"
    client.agents.create_version = AsyncMock(return_value=version_obj)

    return client


# ---------------------------------------------------------------------------
# Async stream helper (kept for backward compatibility with any remaining uses)
# ---------------------------------------------------------------------------

class MockStream:
    """Async context manager that yields pre-defined (event_type, data, _) tuples."""

    def __init__(self, events=()):
        self._events = list(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for event in self._events:
            yield event
