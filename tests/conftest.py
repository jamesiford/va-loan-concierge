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
os.environ.setdefault("KNOWLEDGE_BASE_NAME", "kb-va-loan-test")
os.environ.setdefault("AZURE_AI_SEARCH_ENDPOINT", "https://test-search.search.windows.net")
os.environ.setdefault("PROJECT_RESOURCE_ID", "/subscriptions/00000000/resourceGroups/rg-test/providers/Microsoft.CognitiveServices/accounts/test/projects/test-proj")
os.environ.setdefault("MCP_CONNECTION_NAME", "kb-va-loan-test-mcp")
os.environ.setdefault("MCP_ENDPOINT", "https://test-mcp.azurewebsites.net/mcp")
os.environ.setdefault("MCP_ACTION_CONNECTION_NAME", "va-loan-action-test-conn")


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
) -> MagicMock:
    """
    Build a mock AIProjectClient for AdvisorAgent.

    The agent now references an externally-managed Azure AI Search Knowledge Base;
    no vector store or file upload operations occur at runtime.

    Default: no existing agent → triggers create_version path.
    """
    project_client = MagicMock()

    # agents.get raises ResourceNotFoundError (no existing agent to reuse).
    project_client.agents.get = AsyncMock(
        side_effect=ResourceNotFoundError("not found")
    )

    # create_version returns a version object with .version = "1".
    version_obj = MagicMock()
    version_obj.version = "1"
    project_client.agents.create_version = AsyncMock(return_value=version_obj)

    # Responses API — returns a simple text response with no citations.
    openai_client = MagicMock()
    response = MagicMock()
    response.output = []
    response.output_text = response_text
    openai_client.responses.create = AsyncMock(return_value=response)
    project_client.get_openai_client = MagicMock(return_value=openai_client)

    return project_client


def make_action_mock_client(
    response_text: str = "Your monthly savings are $142.",
) -> MagicMock:
    """
    Build a mock AIProjectClient for ActionAgent.

    Simulates a single Responses API call that returns one mcp_call item
    for refi_savings_calculator (Foundry handles MCP execution server-side).
    """
    client = MagicMock()

    # Agent registration.
    client.agents.get = AsyncMock(side_effect=ResourceNotFoundError("not found"))
    version_obj = MagicMock()
    version_obj.version = "1"
    client.agents.create_version = AsyncMock(return_value=version_obj)

    # Responses API — single call with one mcp_call item in output.
    openai_client = MagicMock()

    mcp_call = MagicMock()
    mcp_call.type = "mcp_call"
    mcp_call.name = "refi_savings_calculator"
    mcp_call.input = {
        "current_rate": 6.8,
        "new_rate": 6.1,
        "balance": 320000,
        "remaining_term": 27,
        "funding_fee_exempt": True,
    }
    mcp_call.output = json.dumps({
        "current_monthly_payment": 2243.17,
        "new_monthly_payment": 2100.67,
        "monthly_savings": 142.50,
        "annual_savings": 1710.0,
        "break_even_months": 29,
        "break_even_years": 2.4,
        "lifetime_savings": 44196.0,
        "closing_costs": 4050.0,
        "is_beneficial": True,
    })

    response = MagicMock()
    response.output = [mcp_call]
    response.output_text = response_text

    openai_client.responses.create = AsyncMock(return_value=response)
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
