"""
Calendar Agent — Foundry Agent + Work IQ Calendar MCP.

This agent creates calendar events on the Veteran's personal M365 calendar
using Microsoft's Work IQ Calendar MCP server.  It is the final agent in
the scheduling pipeline:

  Orchestrator ──► SchedulerAgent (books appointment)
                       │
                       ▼ (confirmed appointment JSON)
                   CalendarAgent (creates M365 calendar event)

Unlike the Calculator and Scheduler agents, this agent does NOT use a custom
MCP server.  It connects to Microsoft's hosted Work IQ Calendar endpoint,
which provides M365-native calendar operations via MCP.

Important: allowed_tools uses the raw MCP tool name ("CreateEvent"), NOT
the Foundry-prefixed name ("mcp_CalendarTools_graph_createEvent").  Using
the prefixed name causes the tools list to return empty.

Required environment variables:
  FOUNDRY_PROJECT_ENDPOINT       — Foundry project data-plane endpoint
  FOUNDRY_MODEL_DEPLOYMENT       — e.g. gpt-4.1
  SCHEDULER_CALENDAR_ENDPOINT    — Work IQ Calendar MCP server URL (Microsoft-hosted)
  SCHEDULER_CALENDAR_CONNECTION  — Foundry project connection name
"""

import asyncio
import json
import logging
import os
from typing import AsyncGenerator

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity.aio import DefaultAzureCredential

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. AGENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# URL-safe agent name — visible in the Foundry portal under Build > Agents.
_AGENT_NAME = "va-loan-calendar-mcp"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AGENT INSTRUCTIONS (the LLM system prompt)
# ═══════════════════════════════════════════════════════════════════════════════
# Very directive instructions — the LLM MUST call CreateEvent and MUST NOT
# skip it.  This agent has the narrowest scope of all agents.

CALENDAR_INSTRUCTIONS = (
    "You are a calendar assistant. Your ONLY job is to call the "
    "CreateEvent tool. You MUST call this tool — "
    "do NOT respond without calling it first.\n\n"
    "IMPORTANT: You must ALWAYS call CreateEvent. "
    "Never skip the tool call. Never respond with text alone.\n\n"
    "Tool parameters:\n"
    "- subject: the appointment type\n"
    "- start: the confirmed date/time in ISO 8601 format\n"
    "- end: 1 hour after start\n"
    "- body: include the loan officer name and confirmation number\n\n"
    "After the tool returns, respond with ONLY:\n"
    "Added to your calendar: [subject] on [date] at [time] with [loan_officer]."
)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AGENT CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class CalendarAgent:
    """
    Calendar Agent powered by Azure AI Foundry + Work IQ Calendar MCP.

    Lifecycle:
      1. initialize() — registers the agent with the Work IQ Calendar tool
      2. run(query)   — calls the Responses API and streams SSE events
      3. close()      — releases async HTTP clients

    No connection provisioning needed — the Work IQ Calendar connection is
    configured manually in the Foundry portal (requires M365 Copilot license).
    """

    def __init__(self) -> None:
        self._credential: DefaultAzureCredential | None = None
        self._client: AIProjectClient | None = None
        self._agent_version: str | None = None

    @property
    def agent_id(self) -> str:
        """Foundry agent version string — available after initialize()."""
        if self._agent_version is None:
            raise RuntimeError("CalendarAgent.initialize() has not been called")
        return self._agent_version

    # ── Client Setup ───────────────────────────────────────────────────────

    def _get_client(self) -> AIProjectClient:
        if self._client is None:
            self._credential = DefaultAzureCredential()
            self._client = AIProjectClient(
                endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                credential=self._credential,
            )
        return self._client

    # ── Agent Registration (initialize) ────────────────────────────────────
    # No connection provisioning needed — unlike the Calculator and Scheduler
    # agents, the Work IQ Calendar connection is managed in the Foundry portal
    # (it requires an OAuth consent flow for M365 calendar access).

    async def initialize(self) -> None:
        """Register a new Foundry agent version with Work IQ Calendar MCP."""
        client = self._get_client()
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

        # MCPTool configuration for Work IQ Calendar:
        #   server_url — Microsoft's hosted MCP endpoint (not our Function App)
        #   allowed_tools — "CreateEvent" is the RAW MCP tool name.
        #     IMPORTANT: Do NOT use the Foundry-prefixed name
        #     "mcp_CalendarTools_graph_createEvent" — that causes the tools
        #     list to return empty and the agent won't call anything.
        calendar_tool = MCPTool(
            server_label="workiq-calendar",
            server_url=os.environ["SCHEDULER_CALENDAR_ENDPOINT"],
            require_approval="never",
            allowed_tools=["CreateEvent"],
            project_connection_id=os.environ["SCHEDULER_CALENDAR_CONNECTION"],
        )

        version_details = await client.agents.create_version(
            agent_name=_AGENT_NAME,
            description="VA Loan Calendar Agent (MCP) — availability check + event creation via Work IQ",
            definition=PromptAgentDefinition(
                model=model,
                instructions=CALENDAR_INSTRUCTIONS,
                tools=[calendar_tool],
            ),
        )
        self._agent_version = version_details.version
        logger.info(
            "calendar_agent: created Foundry agent '%s' version=%s",
            _AGENT_NAME, self._agent_version,
        )

    # ── Run (Main Entry Point) ─────────────────────────────────────────────

    async def run(self, query: str) -> AsyncGenerator[dict, None]:
        """
        Create a calendar event via Work IQ Calendar MCP, streaming SSE events.

        Event sequence:
          calendar_start       → agent activated
          calendar_tool_call   → CreateEvent + inputs
          calendar_tool_result → event created confirmation
          _calendar_text       → full response text (consumed by orchestrator)
        """
        self.last_response = None

        yield {"type": "calendar_start", "message": "Calendar Agent activated"}
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
            logger.exception("calendar_agent: error during agent run")
            yield {"type": "error", "message": f"Calendar agent error: {exc}"}
            return

        self.last_response = response

        for event in self._parse_mcp_events(response):
            yield event
            await asyncio.sleep(0.2)

        response_text: str = response.output_text or ""
        yield {"type": "_calendar_text", "text": response_text}

    # ── MCP Response Parsing ───────────────────────────────────────────────

    def _format_tool_result(self, name: str, raw_output: object) -> str:
        """Format an MCP tool output into a human-readable result message."""
        try:
            data = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
            if name in ("CreateEvent", "mcp_CalendarTools_graph_createEvent"):
                event_id = data.get("eventId") or data.get("id", "")
                return f"Calendar event created (ID: {event_id})" if event_id else "Calendar event created"
        except Exception:
            logger.debug("calendar_agent: could not parse tool result for '%s'", name, exc_info=True)
        return str(raw_output)[:200] if raw_output else f"{name} completed"

    def _parse_mcp_events(self, response) -> list[dict]:
        """
        Extract calendar_tool_call and calendar_tool_result events
        from mcp_call items in response.output.
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
                "type": "calendar_tool_call",
                "message": name,
                "inputs": raw_input,
            })
            events.append({
                "type": "calendar_tool_result",
                "message": self._format_tool_result(name, raw_output),
            })

        return events

    # ── Cleanup ────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release the async HTTP client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        if self._credential is not None:
            await self._credential.close()
            self._credential = None
