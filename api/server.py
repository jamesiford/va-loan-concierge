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
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from main import Orchestrator

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
    logger.info("server: starting up — initializing orchestrator")
    orchestrator = Orchestrator()

    try:
        await orchestrator.initialize()
        app.state.orchestrator = orchestrator
        logger.info("server: orchestrator ready — accepting requests")
    except Exception:
        logger.exception(
            "server: orchestrator initialization failed — "
            "check PROJECT_ENDPOINT, MODEL_DEPLOYMENT_NAME, and az login status"
        )
        app.state.orchestrator = None

    yield

    logger.info("server: shutting down")
    if app.state.orchestrator is not None:
        await app.state.orchestrator.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="VA Loan Concierge API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server (port 5173/5174) and any production origin.
# Tighten allow_origins for production deployments.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    query: str
    profile_id: str | None = None


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
    Final frame:   data: {"type": "final_response", "content": "..."}\n\n

    The stream ends after the final_response event. The client should
    close the connection after receiving it.
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
        try:
            async for event in orchestrator.run(query, profile_id=request.profile_id):
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
