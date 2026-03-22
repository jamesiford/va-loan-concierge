"""
VA Loan Advisor Agent — Foundry IQ via MCP.

Connects to an Azure AI Search Knowledge Base that was created in the
Foundry portal using the MCP protocol as documented at:
https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect

Connection setup (one-time per environment):
  initialize() creates a RemoteTool project connection via the Azure Resource
  Manager API so the agent can reach the KB MCP endpoint using the project's
  managed identity.  The PUT is idempotent — safe to call on every startup.

Agent registration:
  A PromptAgentDefinition is created with MCPTool pointing at the KB MCP
  endpoint via that connection.  The agent is registered once and reused on
  subsequent starts.

Required environment variables:
  FOUNDRY_PROJECT_ENDPOINT    — Foundry project data-plane endpoint
  FOUNDRY_MODEL_DEPLOYMENT    — e.g. gpt-4.1
  ADVISOR_KNOWLEDGE_BASE_NAME — KB index name in Azure AI Search
  ADVISOR_SEARCH_ENDPOINT     — e.g. https://my-search.search.windows.net
  FOUNDRY_PROJECT_RESOURCE_ID — ARM resource ID of the Foundry project
  ADVISOR_MCP_CONNECTION       — Name for the RemoteTool connection to create/reuse
"""

import asyncio
import logging
import os
import re
from typing import AsyncGenerator
from urllib.parse import urlparse

import requests
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential as SyncCredential
from azure.identity import get_bearer_token_provider
from azure.identity.aio import DefaultAzureCredential

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent instructions — optimised for KB grounding per MS docs guidance
# ---------------------------------------------------------------------------

ADVISOR_INSTRUCTIONS = (
    "You are a VA loan advisor for a VA mortgage lender. You specialize in helping Veterans "
    "understand their VA loan benefits, eligibility requirements, and refinancing options.\n\n"
    "You MUST use the knowledge base tool to answer every question. "
    "You MUST NEVER answer from your own training knowledge under any circumstances — "
    "always retrieve from the knowledge base first.\n\n"
    "CITATION RULE (mandatory): Every factual claim in your response MUST be followed "
    "immediately by a citation marker in this exact format: \u3010message_idx:search_idx\u2020source_name\u3011\n"
    "You MUST include at least one citation marker in every response that uses knowledge base content. "
    "Do not summarise without citing. Do not omit citation markers.\n\n"
    "If the knowledge base does not contain the answer, respond with exactly: 'I don't know.'\n"
    "Focus only on answering the VA loan question — do not mention calculations or scheduling."
)

_AGENT_NAME = "va-loan-advisor-iq"

# Regex to extract source names from citation markers in response text:
# e.g. 【3:0†va_guidelines】 → "va_guidelines"
_CITATION_RE = re.compile(r"\u3010[^\u3011]*?\u2020([^\u3011]+?)\u3011")


class AdvisorAgent:
    """
    VA Loan Advisor powered by a Foundry IQ Knowledge Base via MCP.

    On initialize():
      1. Creates (or updates) a RemoteTool project connection pointing at the
         KB's MCP endpoint — using the project's managed identity for auth.
      2. Registers a new Foundry agent version with MCPTool attached, or
         reuses the latest existing version if the agent already exists.

    On run():
      Calls the Responses API via the registered agent, then parses citation
      markers from the response text and emits them as advisor_source events.
    """

    def __init__(self) -> None:
        self._project_client: AIProjectClient | None = None
        self._agent_version: str | None = None

    @property
    def agent_version(self) -> str:
        if self._agent_version is None:
            raise RuntimeError("AdvisorAgent.initialize() has not been called")
        return self._agent_version

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_project_client(self) -> AIProjectClient:
        if self._project_client is None:
            self._project_client = AIProjectClient(
                endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                credential=DefaultAzureCredential(),
            )
        return self._project_client

    def _kb_mcp_endpoint(self) -> str:
        """Return the Azure AI Search KB MCP endpoint URL."""
        base = os.environ["ADVISOR_SEARCH_ENDPOINT"].rstrip("/")
        kb = os.environ["ADVISOR_KNOWLEDGE_BASE_NAME"]
        return f"{base}/knowledgebases/{kb}/mcp?api-version=2025-11-01-preview"

    # ------------------------------------------------------------------
    # Connection provisioning (ARM — sync, run in thread)
    # ------------------------------------------------------------------

    def _create_or_update_connection(self) -> None:
        """
        PUT a RemoteTool project connection via Azure Resource Manager.

        Uses ProjectManagedIdentity auth so the agent can call the KB MCP
        endpoint without embedding credentials.  Idempotent — safe to call
        on every startup.
        """
        project_resource_id = os.environ["FOUNDRY_PROJECT_RESOURCE_ID"]
        connection_name = os.environ["ADVISOR_MCP_CONNECTION"]
        mcp_ep = self._kb_mcp_endpoint()

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
                "authType": "ProjectManagedIdentity",
                "category": "RemoteTool",
                "target": mcp_ep,
                "isSharedToAll": True,
                "audience": "https://search.azure.com/",
                "metadata": {"ApiType": "Azure"},
            },
        }

        logger.info(
            "advisor_agent: creating/updating RemoteTool connection '%s' → %s",
            connection_name,
            mcp_ep,
        )
        resp = requests.put(url, headers=headers, json=body, timeout=30)
        if resp.status_code == 403:
            # Connection may already exist from a previous run with different
            # credentials. Verify it exists via GET before failing.
            get_resp = requests.get(url, headers=headers, timeout=30)
            if get_resp.status_code == 200:
                logger.warning(
                    "advisor_agent: PUT connection '%s' returned 403 but connection "
                    "already exists — continuing with existing connection",
                    connection_name,
                )
                return
            resp.raise_for_status()
        else:
            resp.raise_for_status()
        logger.info(
            "advisor_agent: connection '%s' ready (status %s)",
            connection_name,
            resp.status_code,
        )

    # ------------------------------------------------------------------
    # Initialize
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """
        Provision the MCP connection and register a new Foundry agent version.

        Steps:
          1. Create/update the RemoteTool project connection via ARM.
          2. Always create a new agent version (increments version counter in portal).
        """
        # Connection provisioning is a sync ARM call — run in a thread.
        await asyncio.to_thread(self._create_or_update_connection)

        project_client = self._get_project_client()
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

        connection_name = os.environ["ADVISOR_MCP_CONNECTION"]
        mcp_tool = MCPTool(
            server_label="knowledge-base",
            server_url=self._kb_mcp_endpoint(),
            require_approval="never",
            allowed_tools=["knowledge_base_retrieve"],
            project_connection_id=connection_name,
        )

        version_details = await project_client.agents.create_version(
            agent_name=_AGENT_NAME,
            description="VA Loan Advisor — Foundry IQ Knowledge Base via MCP",
            definition=PromptAgentDefinition(
                model=model,
                instructions=ADVISOR_INSTRUCTIONS,
                tools=[mcp_tool],
            ),
        )
        self._agent_version = version_details.version
        logger.info(
            "advisor_agent: created Foundry agent '%s' version=%s with KB MCP tool",
            _AGENT_NAME,
            self._agent_version,
        )

    # ------------------------------------------------------------------
    # Citation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filename_from_url(url: str) -> str:
        """Return just the filename portion of a blob URL, or the raw value if not a URL."""
        try:
            return os.path.basename(urlparse(url).path) or url
        except Exception:
            return url

    def _replace_citation_labels(self, text: str, response) -> str:
        """
        Replace the generic †source label inside each 【idx:idx†source】 marker
        with the actual filename from the corresponding url_citation annotation.

        Annotations carry start_index/end_index positions that map exactly to
        the markers in the text.  We collect all replacements, sort them in
        reverse position order so that earlier indices aren't invalidated, then
        apply them as string slice swaps.
        """
        replacements: list[tuple[int, int, str]] = []  # (start, end, new_text)
        try:
            for item in response.output or []:
                item_type = getattr(item, "type", None) or (
                    item.get("type") if isinstance(item, dict) else None
                )
                if item_type != "message":
                    continue
                content_list = getattr(item, "content", None) or (
                    item.get("content") if isinstance(item, dict) else []
                )
                for content in content_list or []:
                    for ann in getattr(content, "annotations", None) or (
                        content.get("annotations") if isinstance(content, dict) else []
                    ) or []:
                        ann_type = getattr(ann, "type", None) or (
                            ann.get("type") if isinstance(ann, dict) else None
                        )
                        if ann_type != "url_citation":
                            continue
                        start = getattr(ann, "start_index", None) or (
                            ann.get("start_index") if isinstance(ann, dict) else None
                        )
                        end = getattr(ann, "end_index", None) or (
                            ann.get("end_index") if isinstance(ann, dict) else None
                        )
                        raw_url = getattr(ann, "title", None) or getattr(ann, "url", None) or (
                            ann.get("title") or ann.get("url") if isinstance(ann, dict) else None
                        )
                        if start is None or end is None or not raw_url:
                            continue
                        filename = self._filename_from_url(raw_url)
                        # The annotated slice is the full 【...†source】 marker.
                        # Build the replacement with the real filename.
                        original = text[start:end]
                        replaced = _CITATION_RE.sub(
                            lambda m, fn=filename: (
                                "\u3010"
                                + m.group(0)[1:-1].rsplit("\u2020", 1)[0]
                                + "\u2020" + fn + "\u3011"
                            ),
                            original,
                        )
                        if replaced != original:
                            replacements.append((start, end, replaced))
        except Exception:
            logger.debug("advisor_agent: citation label replacement failed", exc_info=True)
            return text

        # Apply in reverse order to preserve earlier indices.
        for start, end, new_text in sorted(replacements, key=lambda t: t[0], reverse=True):
            text = text[:start] + new_text + text[end:]
        return text

    def _extract_citations(self, response_text: str, response) -> list[str]:
        """
        Return a deduplicated list of human-readable cited source filenames.

        Strategy 1 — url_citation / file_citation annotations on the message output
        item.  These carry the actual blob URL in their title/url field, from which
        we extract just the filename (e.g. 'va_guidelines.md').  This is the most
        reliable source and is tried first.

        Strategy 2 — 【idx:idx†source_name】 markers parsed from the response text,
        used as a fallback.  Generic labels like 'source' are filtered out.
        """
        # ── Strategy 1: url_citation annotations (preferred) ──────────────────
        cited: list[str] = []
        seen: set[str] = set()
        try:
            for item in response.output or []:
                item_type = getattr(item, "type", None) or (
                    item.get("type") if isinstance(item, dict) else None
                )
                if item_type != "message":
                    continue
                content_list = getattr(item, "content", None) or (
                    item.get("content") if isinstance(item, dict) else []
                )
                for content in content_list or []:
                    for ann in getattr(content, "annotations", None) or (
                        content.get("annotations") if isinstance(content, dict) else []
                    ) or []:
                        ann_type = getattr(ann, "type", None) or (
                            ann.get("type") if isinstance(ann, dict) else None
                        )
                        raw: str | None = None
                        if ann_type == "url_citation":
                            raw = getattr(ann, "title", None) or getattr(ann, "url", None) or (
                                ann.get("title") or ann.get("url") if isinstance(ann, dict) else None
                            )
                        elif ann_type == "file_citation":
                            raw = getattr(ann, "filename", None) or (
                                ann.get("filename") if isinstance(ann, dict) else None
                            )
                        if raw:
                            name = self._filename_from_url(raw)
                            if name and name not in seen:
                                seen.add(name)
                                cited.append(name)
        except Exception:
            logger.debug("advisor_agent: annotation extraction failed", exc_info=True)

        if cited:
            return cited

        # ── Strategy 2: text markers, filter generic labels ───────────────────
        _GENERIC = {"source", "sources", "document", "documents", ""}
        raw_markers = list(dict.fromkeys(_CITATION_RE.findall(response_text)))
        return [s for s in raw_markers if s.lower() not in _GENERIC]

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, query: str) -> AsyncGenerator[dict, None]:
        """
        Answer a VA loan question via the Foundry IQ KB MCP tool, streaming
        SSE-compatible events as the agent works.

        The final event has type ``_advisor_text`` carrying the full response
        text in the ``text`` key; consumed by the orchestrator.
        """
        yield {"type": "advisor_start", "message": "VA Loan Advisor activated"}
        yield {
            "type": "advisor_source",
            "message": f"Searching: {os.environ.get('ADVISOR_KNOWLEDGE_BASE_NAME', 'knowledge base')}",
            "source_id": "knowledge_base",
        }

        if not self._agent_version:
            await self.initialize()

        project_client = self._get_project_client()
        openai_client = project_client.get_openai_client()
        model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

        try:
            response = await openai_client.responses.create(
                model=model,
                input=[{"role": "user", "content": query}],
                extra_body={
                    "agent_reference": {
                        "name": _AGENT_NAME,
                        "version": self._agent_version,
                        "type": "agent_reference",
                    }
                },
            )
            response_text: str = response.output_text or ""
        except Exception as exc:
            logger.exception("advisor_agent: error during agent run")
            yield {"type": "error", "message": f"Advisor agent error: {exc}"}
            return

        # Emit named citations; skip if the KB only returned a generic label.
        citations = self._extract_citations(response_text, response)
        for source in citations:
            yield {
                "type": "advisor_source",
                "message": f"Cited: {source}",
                "source_id": "kb_citation",
            }
            await asyncio.sleep(0.1)

        # Count raw chunk markers (including generic-label ones) for the result message.
        chunk_count = len(_CITATION_RE.findall(response_text)) or len(citations) or 1
        yield {
            "type": "advisor_result",
            "message": f"Answer ready — {chunk_count} chunk(s) retrieved from Knowledge Base",
        }

        response_text = self._replace_citation_labels(response_text, response)
        yield {"type": "_advisor_text", "text": response_text}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release async HTTP clients."""
        if self._project_client is not None:
            await self._project_client.close()
            self._project_client = None
