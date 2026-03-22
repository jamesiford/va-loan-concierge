"""
Loan Calculator Agent — Foundry new-agent API with Azure-hosted MCP.

Connects to an Azure Function App MCP server (mcp-server/) that exposes:
  - refi_savings_calculator  : VA IRRRL refinance savings

This agent is restricted to calculation tools only.  Scheduling and
appointment tools are handled by the Scheduler Agent.

The MCP endpoint URL is read from MCP_ENDPOINT.  The Foundry runtime
handles all MCP tool execution; this agent registers the tool definitions
via MCPTool and makes a single Responses API call per query.

After the call, response.output is inspected for mcp_call items — these
carry the tool name, inputs, and outputs — and are emitted as
calculator_tool_call / calculator_tool_result SSE events for the UI flow log.
"""

import asyncio
import json
import logging
import os
from typing import AsyncGenerator

import requests
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential as SyncCredential
from azure.identity import get_bearer_token_provider
from azure.identity.aio import DefaultAzureCredential

logger = logging.getLogger(__name__)

_AGENT_NAME = "va-loan-calculator-mcp"

CALCULATOR_INSTRUCTIONS = (
    "You are a VA loan calculator assistant. You help Veterans understand the "
    "financial impact of refinancing their VA loan.\n\n"
    "When asked to calculate refinance savings, call refi_savings_calculator with the "
    "loan parameters provided.\n\n"
    "After receiving tool results, present the information clearly and helpfully. "
    "Lead with the monthly savings figure, highlight the break-even timeline, and state "
    "whether the IRRRL passes the VA net tangible benefit test.\n\n"
    "You do NOT handle appointment scheduling — that is handled by a separate agent."
)


class CalculatorAgent:
    """
    Loan Calculator Agent powered by Azure AI Foundry new-agent API + Azure-hosted MCP.

    On initialize():
      Registers the agent with MCPTool pointing at MCP_ENDPOINT, restricted
      to calculation tools only.

    On run():
      Makes a single Responses API call.  The Foundry runtime invokes the
      MCP tools server-side; response.output contains mcp_call items that
      are parsed into calculator_tool_call / calculator_tool_result SSE events.
    """

    def __init__(self) -> None:
        self._client: AIProjectClient | None = None
        self._agent_version: str | None = None

    @property
    def agent_id(self) -> str:
        """Foundry agent version string — available after initialize()."""
        if self._agent_version is None:
            raise RuntimeError("CalculatorAgent.initialize() has not been called")
        return self._agent_version

    # ------------------------------------------------------------------
    # Connection provisioning (ARM — sync, run in thread)
    # ------------------------------------------------------------------

    def _create_or_update_connection(self) -> None:
        """
        PUT a RemoteTool project connection pointing at the MCP Function App.

        Idempotent — safe to call on every startup.
        """
        project_resource_id = os.environ["FOUNDRY_PROJECT_RESOURCE_ID"]
        connection_name = os.environ["MCP_TOOLS_CONNECTION"]
        mcp_ep = os.environ["MCP_TOOLS_ENDPOINT"]

        cred = SyncCredential()
        token_provider = get_bearer_token_provider(
            cred, "https://management.azure.com/.default"
        )
        headers = {"Authorization": f"Bearer {token_provider()}"}

        url = (
            f"https://management.azure.com{project_resource_id}"
            f"/connections/{connection_name}?api-version=2025-10-01-preview"
        )
        body = {
            "name": connection_name,
            "type": "Microsoft.MachineLearningServices/workspaces/connections",
            "properties": {
                "authType": "None",
                "category": "RemoteTool",
                "target": mcp_ep,
                "isSharedToAll": True,
                "metadata": {"ApiType": "Azure"},
            },
        }

        logger.info(
            "calculator_agent: creating/updating RemoteTool connection '%s' → %s",
            connection_name,
            mcp_ep,
        )
        resp = requests.put(url, headers=headers, json=body, timeout=30)
        if resp.status_code == 403:
            get_resp = requests.get(url, headers=headers, timeout=30)
            if get_resp.status_code == 200:
                logger.warning(
                    "calculator_agent: PUT connection '%s' returned 403 but connection "
                    "already exists — continuing with existing connection",
                    connection_name,
                )
                return
            resp.raise_for_status()
        else:
            resp.raise_for_status()
        logger.info(
            "calculator_agent: connection '%s' ready (status %s)",
            connection_name,
            resp.status_code,
        )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _get_client(self) -> AIProjectClient:
        if self._client is None:
            self._client = AIProjectClient(
                endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                credential=DefaultAzureCredential(),
            )
        return self._client

    async def initialize(self) -> None:
        """Provision the MCP connection and register a new Foundry agent version."""
        await asyncio.to_thread(self._create_or_update_connection)

        client = self._get_client()
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

        mcp_tool = MCPTool(
            server_label="va-loan-tools",
            server_url=os.environ["MCP_TOOLS_ENDPOINT"],
            require_approval="never",
            allowed_tools=["refi_savings_calculator"],
            project_connection_id=os.environ["MCP_TOOLS_CONNECTION"],
        )
        version_details = await client.agents.create_version(
            agent_name=_AGENT_NAME,
            description="VA Loan Calculator Agent (MCP) — IRRRL refinance savings calculator",
            definition=PromptAgentDefinition(
                model=model,
                instructions=CALCULATOR_INSTRUCTIONS,
                tools=[mcp_tool],
            ),
        )
        self._agent_version = version_details.version
        logger.info(
            "calculator_agent: created Foundry agent '%s' version=%s with MCP tools",
            _AGENT_NAME,
            self._agent_version,
        )

    # ------------------------------------------------------------------
    # MCP output parsing
    # ------------------------------------------------------------------

    def _format_tool_result(self, name: str, raw_output: object) -> str:
        """
        Format an MCP tool output into a human-readable result message.

        raw_output is typically a JSON string returned by the MCP server.
        Falls back to a truncated string representation on any parse error.
        """
        try:
            data = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
            if name == "refi_savings_calculator":
                benefit = (
                    "✓ passes VA net tangible benefit test"
                    if data.get("is_beneficial")
                    else "✗ fails VA net tangible benefit test"
                )
                return (
                    f"Monthly savings: ${data['monthly_savings']:,.2f} | "
                    f"Annual savings: ${data['annual_savings']:,.2f} | "
                    f"Break-even: {data['break_even_months']} months | "
                    f"{benefit}"
                )
        except Exception:
            logger.debug("calculator_agent: could not parse tool result for '%s'", name, exc_info=True)
        return str(raw_output)[:200] if raw_output else f"{name} completed"

    def _parse_mcp_events(self, response) -> list[dict]:
        """
        Extract calculator_tool_call and calculator_tool_result events from
        mcp_call items in response.output.
        """
        events: list[dict] = []
        for item in response.output or []:
            item_type = getattr(item, "type", None) or (
                item.get("type") if isinstance(item, dict) else None
            )
            if item_type != "mcp_call":
                continue

            name: str = getattr(item, "name", None) or (
                item.get("name") if isinstance(item, dict) else ""
            ) or ""

            raw_input = getattr(item, "input", None) or (
                item.get("input") if isinstance(item, dict) else {}
            ) or {}
            if isinstance(raw_input, str):
                try:
                    raw_input = json.loads(raw_input)
                except Exception:
                    raw_input = {}

            raw_output = getattr(item, "output", None) or (
                item.get("output") if isinstance(item, dict) else ""
            ) or ""

            events.append({
                "type": "calculator_tool_call",
                "message": name,
                "inputs": raw_input,
            })
            events.append({
                "type": "calculator_tool_result",
                "message": self._format_tool_result(name, raw_output),
            })

        return events

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, query: str) -> AsyncGenerator[dict, None]:
        """
        Execute loan calculator tools via MCP and stream SSE-compatible events.

        The final event has ``type == "_calculator_text"`` carrying the
        formatted response text; consumed by the orchestrator.
        """
        yield {"type": "calculator_start", "message": "Loan Calculator Agent activated"}
        await asyncio.sleep(0.1)

        if not self._agent_version:
            await self.initialize()

        client = self._get_client()
        openai_client = client.get_openai_client()
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

        try:
            response = await openai_client.responses.create(
                model=model,
                input=[{"role": "user", "content": query}],
                max_tool_calls=1,
                extra_body={
                    "agent_reference": {
                        "name": _AGENT_NAME,
                        "version": self._agent_version,
                        "type": "agent_reference",
                    }
                },
            )
        except Exception as exc:
            logger.exception("calculator_agent: error during agent run")
            yield {"type": "error", "message": f"Calculator agent error: {exc}"}
            return

        for event in self._parse_mcp_events(response):
            yield event
            await asyncio.sleep(0.2)

        response_text: str = response.output_text or ""
        yield {"type": "_calculator_text", "text": response_text}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release the async HTTP client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
