"""
VA Loan Advisor Agent — Foundry IQ / knowledge base agent.

Answers VA loan eligibility, product, and process questions using a real
Azure AI Foundry FileSearch (Foundry IQ) vector store. Knowledge source
markdown files are uploaded to the agent service and indexed in a vector
store; the agent performs grounded RAG over them at query time.

The agent is registered via AIProjectClient.agents.create_version() which
creates a "new agent" (not a classic assistant) visible in the Foundry portal.
Vector store creation still uses AgentsClient (the only API that supports
file upload and vector store management).
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, FileSearchTool
from azure.ai.agents.aio import AgentsClient
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Knowledge source registry
# ---------------------------------------------------------------------------

KNOWLEDGE_SOURCES: list[dict] = [
    {
        "id": "va_guidelines",
        "filename": "va_guidelines.md",
        "label": "VA Guidelines",
        "keywords": [
            "eligib", "irrrl", "coe", "certificate of eligibility", "entitlement",
            "funding fee", "mpr", "minimum property", "benefit", "discharge",
            "service", "veteran", "occupancy", "guarantee", "surviving spouse",
        ],
    },
    {
        "id": "lender_products",
        "filename": "lender_products.md",
        "label": "Lender Products",
        "keywords": [
            "product", "rate", "loan officer", "jumbo", "renovation", "overlay",
            "credit score", "dti", "cash-out", "rate lock", "lender",
            "sarah chen", "marcus williams", "priya patel", "apr",
        ],
    },
    {
        "id": "loan_process_faq",
        "filename": "loan_process_faq.md",
        "label": "Loan Process FAQ",
        "keywords": [
            "process", "step", "faq", "myth", "second time", "again", "appraisal",
            "closing", "deployed", "timeline", "how long", "can i", "what is",
            "misconception", "common question",
        ],
    },
]

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

# Agent instructions — no knowledge content here; that lives in the vector store.
ADVISOR_INSTRUCTIONS = (
    "You are a VA loan advisor for a VA mortgage lender. You specialize in helping Veterans "
    "understand their VA loan benefits, eligibility requirements, and refinancing options.\n\n"
    "Answer questions accurately and completely by searching your knowledge base. "
    "Always cite which document supports each part of your answer. "
    "If information is not found in the knowledge base, say so clearly — do not speculate "
    "or invent figures. Keep answers clear and helpful. "
    "Defer all requests for calculations or appointment scheduling to the action agent."
)

# URL-safe agent name for the new Foundry agent API (alphanumeric + hyphens, max 63 chars).
_AGENT_NAME = "va-loan-advisor"
_VECTOR_STORE_NAME = "VA Knowledge Base"


class AdvisorAgent:
    """
    VA Loan Advisor powered by Azure AI Foundry IQ (FileSearch).

    Uses AIProjectClient.agents.create_version() to register the agent as a
    "new agent" in the Foundry portal (not a classic assistant). AgentsClient
    is retained only for vector store and file upload operations.

    On first initialization, uploads the three knowledge source markdown
    files, creates a named vector store, and registers a new agent version
    pointing at that vector store. On subsequent initializations, the
    existing vector store and agent version are reused.

    Usage::

        agent = AdvisorAgent()
        await agent.initialize()
        async for event in agent.run(query):
            process_event(event)
        await agent.close()
    """

    def __init__(self) -> None:
        self._project_client: AIProjectClient | None = None
        self._agents_client: AgentsClient | None = None
        self._agent_version: str | None = None
        self._vector_store_id: str | None = None
        self._knowledge: dict[str, str] = self._load_knowledge()

    def _load_knowledge(self) -> dict[str, str]:
        """Load knowledge source content from disk at construction time."""
        result: dict[str, str] = {}
        for source in KNOWLEDGE_SOURCES:
            path = KNOWLEDGE_DIR / source["filename"]
            try:
                result[source["id"]] = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                logger.warning("advisor_agent: knowledge file not found: %s", path)
                result[source["id"]] = ""
        return result

    @property
    def agent_version(self) -> str:
        """Foundry agent version — available after initialize() has been called."""
        if self._agent_version is None:
            raise RuntimeError("AdvisorAgent.initialize() has not been called")
        return self._agent_version

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _get_project_client(self) -> AIProjectClient:
        """Return the AIProjectClient used for agent registration and running."""
        if self._project_client is None:
            self._project_client = AIProjectClient(
                endpoint=os.environ["PROJECT_ENDPOINT"],
                credential=DefaultAzureCredential(),
            )
        return self._project_client

    def _get_agents_client(self) -> AgentsClient:
        """Return the AgentsClient used only for vector store and file operations."""
        if self._agents_client is None:
            self._agents_client = AgentsClient(
                endpoint=os.environ["PROJECT_ENDPOINT"],
                credential=DefaultAzureCredential(),
            )
        return self._agents_client

    async def _get_or_create_vector_store(self, client: AgentsClient) -> str:
        """
        Return the ID of the 'VA Knowledge Base' vector store, creating it
        (and uploading the knowledge files) if it does not yet exist.
        """
        try:
            async for vs in client.vector_stores.list():
                if vs.name == _VECTOR_STORE_NAME:
                    logger.info(
                        "advisor_agent: reusing vector store '%s' id=%s",
                        _VECTOR_STORE_NAME,
                        vs.id,
                    )
                    return vs.id
        except Exception:
            logger.debug("advisor_agent: could not list vector stores — will create new")

        file_ids: list[str] = []
        for source in KNOWLEDGE_SOURCES:
            path = KNOWLEDGE_DIR / source["filename"]
            if not path.exists():
                logger.warning(
                    "advisor_agent: knowledge file not found, skipping: %s", path
                )
                continue

            logger.info(
                "advisor_agent: uploading '%s' to Foundry agent service", source["filename"]
            )
            uploaded = await client.files.upload_and_poll(
                file_path=str(path),
                purpose="assistants",
            )
            file_ids.append(uploaded.id)
            logger.info(
                "advisor_agent: uploaded '%s' → file_id=%s",
                source["filename"],
                uploaded.id,
            )

        if not file_ids:
            raise RuntimeError(
                "advisor_agent: no knowledge files were uploaded — "
                "check that the knowledge/ directory exists and contains .md files"
            )

        logger.info(
            "advisor_agent: creating vector store '%s' from %d file(s)",
            _VECTOR_STORE_NAME,
            len(file_ids),
        )
        vector_store = await client.vector_stores.create_and_poll(
            file_ids=file_ids,
            name=_VECTOR_STORE_NAME,
        )
        logger.info(
            "advisor_agent: vector store '%s' ready id=%s",
            _VECTOR_STORE_NAME,
            vector_store.id,
        )
        return vector_store.id

    async def initialize(self) -> None:
        """
        Create or retrieve the Foundry agent and its knowledge base.

        Steps:
        1. Find or create the 'VA Knowledge Base' vector store (uploading
           markdown files if needed) via AgentsClient.
        2. Register a new agent version via AIProjectClient.agents.create_version(),
           or reuse the latest existing version if the agent already exists.

        After this call the agent appears as a 'new agent' in the Foundry
        portal with its FileSearch knowledge base attached.
        """
        agents_client = self._get_agents_client()
        self._vector_store_id = await self._get_or_create_vector_store(agents_client)

        project_client = self._get_project_client()
        model = os.environ["MODEL_DEPLOYMENT_NAME"]
        file_search = FileSearchTool(vector_store_ids=[self._vector_store_id])

        # Reuse existing agent version if available.
        try:
            existing = await project_client.agents.get(_AGENT_NAME)
            self._agent_version = existing.versions.latest.version
            logger.info(
                "advisor_agent: reusing existing Foundry agent '%s' version=%s",
                _AGENT_NAME,
                self._agent_version,
            )
            return
        except ResourceNotFoundError:
            logger.debug("advisor_agent: no existing agent found — will create new version")

        version_details = await project_client.agents.create_version(
            agent_name=_AGENT_NAME,
            description="VA Loan Advisor — Foundry IQ knowledge base agent",
            definition=PromptAgentDefinition(
                model=model,
                instructions=ADVISOR_INSTRUCTIONS,
                tools=[file_search],
            ),
        )
        self._agent_version = version_details.version
        logger.info(
            "advisor_agent: created Foundry agent '%s' version=%s with vector store id=%s",
            _AGENT_NAME,
            self._agent_version,
            self._vector_store_id,
        )

    # ------------------------------------------------------------------
    # Knowledge relevance (UI hint — pre-query source labeling)
    # ------------------------------------------------------------------

    def _relevant_sources(self, query: str) -> list[dict]:
        """
        Score knowledge sources by keyword relevance to the query.

        These labels are used to emit advisor_source events before the agent
        runs — giving the UI something to show immediately. The actual
        retrieval is performed by Foundry IQ (FileSearch) at run time.
        va_guidelines is always included as it covers the broadest set of
        VA eligibility questions.
        """
        query_lower = query.lower()
        scored: list[tuple[int, dict]] = []

        for source in KNOWLEDGE_SOURCES:
            hits = sum(1 for kw in source["keywords"] if kw in query_lower)
            if hits > 0 or source["id"] == "va_guidelines":
                scored.append((hits, source))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [s for _, s in scored]

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, query: str) -> AsyncGenerator[dict, None]:
        """
        Answer a VA loan question using Foundry IQ (FileSearch), streaming
        SSE-compatible events as the agent works.

        Yields dicts with at least a ``type`` and ``message`` key.
        The final event has ``type == "_advisor_text"`` and carries the full
        response text in the ``text`` key; consumed by the orchestrator.
        """
        yield {"type": "advisor_start", "message": "VA Loan Advisor activated"}

        # Emit pre-query source hints so the UI shows activity immediately.
        relevant = self._relevant_sources(query)
        for source in relevant:
            yield {
                "type": "advisor_source",
                "message": f"Querying: {source['filename']}",
                "source_id": source["id"],
            }
            await asyncio.sleep(0.25)

        # Ensure agent and vector store are initialized.
        if not self._agent_version:
            await self.initialize()

        project_client = self._get_project_client()
        openai_client = project_client.get_openai_client()
        model = os.environ["MODEL_DEPLOYMENT_NAME"]

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

        yield {
            "type": "advisor_result",
            "message": f"Answer ready — {len(relevant)} source(s) searched via Foundry IQ",
        }

        # Internal event carrying the response text; consumed by orchestrator.
        yield {"type": "_advisor_text", "text": response_text}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release async HTTP clients."""
        if self._project_client is not None:
            await self._project_client.close()
            self._project_client = None
        if self._agents_client is not None:
            await self._agents_client.close()
            self._agents_client = None
