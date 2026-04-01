"""
VA Loan Concierge — FastAPI server

Exposes a single POST /api/chat endpoint that accepts a JSON body
{"query": "..."} and streams the orchestrator's SSE events back to
the client as a text/event-stream response.

Each SSE frame carries one newline-delimited JSON event matching the
schema defined in CLAUDE.md. The UI's useAgentStream hook consumes
this stream and renders events in real time.

Run with:
    uvicorn api.server:app --reload --port 8000
"""

import json
import logging
import os
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dotenv import load_dotenv

from agents.orchestrator_agent import Orchestrator
from api.conversation_state import init_store, close_store
from api.telemetry import setup_telemetry, get_tracer

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application lifespan — initialize orchestrator once at startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize the Orchestrator (and therefore all Foundry agents) at server
    startup. This ensures the vector store upload and agent registrations
    happen once — not on the first request — so the first user interaction
    is fast.

    Initialization can take 10–30 seconds on the very first run while
    knowledge files are uploaded and indexed by Foundry. Subsequent starts
    are fast (existing agents and vector store are reused).
    """
    setup_telemetry(app)

    # -- Cosmos DB state backend (or in-memory fallback) --
    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT")
    cosmos_container = None
    cosmos_client = None

    if cosmos_endpoint:
        try:
            from azure.cosmos.aio import CosmosClient
            from azure.identity.aio import DefaultAzureCredential as AsyncCredential

            cosmos_credential = AsyncCredential()
            cosmos_client = CosmosClient(cosmos_endpoint, credential=cosmos_credential)
            database = cosmos_client.get_database_client("va-loan-concierge")
            cosmos_container = database.get_container_client("conversation-state")
            logger.info("server: Cosmos DB client initialized → %s", cosmos_endpoint)
        except Exception:
            logger.warning(
                "server: Cosmos DB init failed — falling back to in-memory state",
                exc_info=True,
            )
            cosmos_container = None

    await init_store(cosmos_container)

    logger.info("server: starting up — initializing orchestrator")
    orchestrator = Orchestrator()

    try:
        await orchestrator.initialize()
        app.state.orchestrator = orchestrator
        logger.info("server: orchestrator ready — accepting requests")
    except Exception:
        logger.exception(
            "server: orchestrator initialization failed — "
            "check FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_DEPLOYMENT, and az login status"
        )
        app.state.orchestrator = None

    yield

    logger.info("server: shutting down")
    if app.state.orchestrator is not None:
        await app.state.orchestrator.close()
    await close_store()
    if cosmos_client is not None:
        await cosmos_client.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="VA Loan Concierge API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server and the production App Service origin.
# In production the static files are served from the same origin, so CORS
# is not needed — but keeping localhost allows local dev to work unchanged.
_cors_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]
_web_app_origin = os.environ.get("WEB_APP_ORIGIN")
if _web_app_origin:
    _cors_origins.append(_web_app_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    query: str
    profile_id: str | None = None
    conversation_id: str | None = None


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse_frame(event: dict) -> str:
    """Serialize one event dict to an SSE data frame."""
    return f"data: {json.dumps(event)}\n\n"


def _error_frame(message: str) -> str:
    return _sse_frame({"type": "error", "message": message})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    """
    Health check used by the UI's StatusDot component.
    Returns 200 with orchestrator readiness status.
    """
    ready = getattr(app.state, "orchestrator", None) is not None
    return {"status": "ok", "orchestrator_ready": ready}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Stream an orchestrator response as Server-Sent Events.

    Request body:  {"query": "<Veteran's question>"}
    Response:      text/event-stream — one JSON event per SSE frame.

    Each frame:    data: {"type": "...", "message": "..."}\n\n

    Agent results arrive as partial_response events — one per agent —
    so the UI can display each section as it becomes available. The
    stream ends after the complete event.
    """
    orchestrator: Orchestrator | None = getattr(app.state, "orchestrator", None)

    if orchestrator is None:
        async def init_error():
            yield _error_frame(
                "Orchestrator is not initialized. Check server logs for details."
            )
        return StreamingResponse(
            init_error(),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    query = request.query.strip()
    if not query:
        async def empty_query():
            yield _error_frame("Query must not be empty.")
        return StreamingResponse(
            empty_query(),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    logger.info("server: received query — %r", query[:120])

    async def event_stream():
        tracer = get_tracer()
        with tracer.start_as_current_span(
            "chat_request",
            attributes={
                "chat.query": query[:500],
                "chat.profile_id": request.profile_id or "none",
                "chat.conversation_id": request.conversation_id or "new",
            },
        ):
            try:
                async for event in orchestrator.run(
                    query,
                    profile_id=request.profile_id,
                    conversation_id=request.conversation_id,
                ):
                    yield _sse_frame(event)
            except Exception as exc:
                logger.exception("server: unhandled error during orchestration")
                yield _error_frame(f"Server error: {exc}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",   # prevents nginx/proxy from buffering the stream
        "Connection": "keep-alive",
    }


# ---------------------------------------------------------------------------
# Newsletter / Market Intelligence endpoints
# ---------------------------------------------------------------------------

@app.post("/api/newsletter")
async def newsletter_stream():
    """
    Trigger a newsletter digest run and stream results as SSE.
    Sends the weekly digest query through the orchestrator and streams
    newsletter_start / newsletter_tool_call / newsletter_tool_result /
    _newsletter_text / newsletter_complete events.
    """
    orchestrator: Orchestrator | None = getattr(app.state, "orchestrator", None)

    if orchestrator is None:
        async def init_error():
            yield _sse_frame({"type": "error", "message": "Orchestrator not initialized."})
        return StreamingResponse(init_error(), media_type="text/event-stream", headers=_sse_headers())

    async def event_stream():
        try:
            async for event in orchestrator.run(
                "Generate the weekly market intelligence digest",
                profile_id=None,
                conversation_id=None,
            ):
                yield _sse_frame(event)
        except Exception as exc:
            logger.exception("server: newsletter stream error")
            yield _sse_frame({"type": "error", "message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_sse_headers())


@app.get("/api/signals/config")
async def signals_config():
    """
    Returns the static demo client configuration for the Market Intelligence UI.
    In a production system this would be read from a database.
    """
    return {
        "client": "Experian",
        "sector": "credit-bureau",
        "digest_day": "Monday",
        "watchlist": ["Equifax", "TransUnion", "FICO", "Moodys", "Dun & Bradstreet"],
        "competitors": ["Equifax", "TransUnion"],
        "topics": ["regulatory", "ai-lending", "data-privacy", "credit-scoring", "consumer-credit", "CFPB"],
        "distribution": ["chris.shanku@ilink-systems.com"],
    }


# ---------------------------------------------------------------------------
# Static files — serve React production build (Phase 5)
# ---------------------------------------------------------------------------
# Must be AFTER all API route definitions so /api/* routes take priority.
# The html=True parameter serves index.html as fallback for SPA client-side
# routing. In local dev (no static/ dir), this mount is simply skipped.
# ---------------------------------------------------------------------------

_static_dir = pathlib.Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
