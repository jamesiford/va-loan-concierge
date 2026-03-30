"""
Persistent conversation state for human-in-the-loop flows.

Tracks multi-turn conversations where the orchestrator pauses to collect
user input (e.g., missing profile info, appointment confirmation).

Two backends:
  - **Cosmos DB** (production): set COSMOS_ENDPOINT env var. Documents auto-expire
    via Cosmos TTL (600 s). State survives server restarts.
  - **In-memory dict** (local dev / tests): used when COSMOS_ENDPOINT is absent.
    State is ephemeral — lost on server restart.

All public functions are async.  The orchestrator calls them with ``await``.
"""

import dataclasses
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# State expires after 10 minutes of inactivity.
_TTL_SECONDS = 600


@dataclass
class ConversationState:
    conversation_id: str
    profile_id: str | None = None
    original_query: str = ""
    enriched_query: str = ""

    # Routing decisions (preserved across turns)
    needs_advisor: bool = False
    needs_calculator: bool = False
    needs_scheduler: bool = False

    # Agent results accumulated across turns
    advisor_text: str = ""
    calculator_text: str = ""
    scheduler_text: str = ""
    appointment_json: str | None = None

    # True when the user manually provided loan details via HIL prompt
    # (skips _demo_context_block for calculator — user's details are already in enriched_query)
    user_provided_details: bool = False

    # Calculator retry count (max 3 attempts before forcing defaults)
    calculator_retry_count: int = 0

    # What we're waiting for the user to provide
    # Values: None | "awaiting_profile_info" | "awaiting_calculator_retry"
    #       | "awaiting_appointment_confirmation"
    pending_action: str | None = None

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.updated_at) > _TTL_SECONDS


# ---------------------------------------------------------------------------
# Backend interface — set by init_store()
# ---------------------------------------------------------------------------

_backend: "_StateBackend | None" = None


class _StateBackend:
    """Abstract base for state backends."""

    async def create(self, state: ConversationState) -> None:
        raise NotImplementedError

    async def get(self, conversation_id: str) -> ConversationState | None:
        raise NotImplementedError

    async def save(self, state: ConversationState) -> None:
        raise NotImplementedError

    async def delete(self, conversation_id: str) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# In-memory backend (local dev / tests)
# ---------------------------------------------------------------------------

class _InMemoryBackend(_StateBackend):
    def __init__(self) -> None:
        self._store: dict[str, ConversationState] = {}

    async def create(self, state: ConversationState) -> None:
        self._cleanup_expired()
        self._store[state.conversation_id] = state

    async def get(self, conversation_id: str) -> ConversationState | None:
        state = self._store.get(conversation_id)
        if state is None:
            return None
        if state.is_expired:
            self._store.pop(conversation_id, None)
            return None
        state.touch()
        return state

    async def save(self, state: ConversationState) -> None:
        state.touch()
        self._store[state.conversation_id] = state

    async def delete(self, conversation_id: str) -> None:
        self._store.pop(conversation_id, None)

    def _cleanup_expired(self) -> None:
        expired = [k for k, v in self._store.items() if v.is_expired]
        for k in expired:
            del self._store[k]


# ---------------------------------------------------------------------------
# Cosmos DB backend (production)
# ---------------------------------------------------------------------------

class _CosmosBackend(_StateBackend):
    """Async Cosmos DB NoSQL backend for conversation state."""

    def __init__(self, container: Any) -> None:
        # container is azure.cosmos.aio.ContainerProxy
        self._container = container

    def _to_doc(self, state: ConversationState) -> dict:
        doc = dataclasses.asdict(state)
        doc["id"] = state.conversation_id
        doc["ttl"] = _TTL_SECONDS
        return doc

    def _from_doc(self, doc: dict) -> ConversationState:
        fields = {f.name for f in dataclasses.fields(ConversationState)}
        return ConversationState(**{k: v for k, v in doc.items() if k in fields})

    async def create(self, state: ConversationState) -> None:
        await self._container.upsert_item(self._to_doc(state))
        logger.info("conversation_state: Cosmos create(%s) OK", state.conversation_id)

    async def get(self, conversation_id: str) -> ConversationState | None:
        try:
            doc = await self._container.read_item(
                item=conversation_id,
                partition_key=conversation_id,
            )
            state = self._from_doc(doc)
            state.touch()
            # Upsert to reset Cosmos _ts (extends TTL)
            await self._container.upsert_item(self._to_doc(state))
            return state
        except Exception as exc:
            logger.warning(
                "conversation_state: Cosmos get(%s) failed — %s: %s",
                conversation_id, type(exc).__name__, exc,
            )
            return None

    async def save(self, state: ConversationState) -> None:
        state.touch()
        await self._container.upsert_item(self._to_doc(state))
        logger.debug("conversation_state: Cosmos save(%s) OK", state.conversation_id)

    async def delete(self, conversation_id: str) -> None:
        try:
            await self._container.delete_item(
                item=conversation_id,
                partition_key=conversation_id,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

async def init_store(cosmos_container: Any = None) -> None:
    """
    Initialize the state backend.

    Args:
        cosmos_container: An ``azure.cosmos.aio.ContainerProxy`` instance.
            If provided, Cosmos DB is used.  Otherwise falls back to in-memory.
    """
    global _backend
    if cosmos_container is not None:
        _backend = _CosmosBackend(cosmos_container)
        logger.info("conversation_state: using Cosmos DB backend")
    else:
        _backend = _InMemoryBackend()
        logger.info("conversation_state: using in-memory backend (no COSMOS_ENDPOINT)")


async def close_store() -> None:
    """Release backend resources."""
    global _backend
    if _backend is not None:
        await _backend.close()
        _backend = None


def _get_backend() -> _StateBackend:
    if _backend is None:
        raise RuntimeError(
            "conversation_state not initialized — call init_store() first"
        )
    return _backend


# ---------------------------------------------------------------------------
# Public API (async)
# ---------------------------------------------------------------------------

async def create_conversation(
    profile_id: str | None = None,
    original_query: str = "",
) -> ConversationState:
    """Create a new conversation and return its state."""
    state = ConversationState(
        conversation_id=uuid.uuid4().hex[:12],
        profile_id=profile_id,
        original_query=original_query,
    )
    await _get_backend().create(state)
    return state


async def get_conversation(conversation_id: str) -> ConversationState | None:
    """Look up a conversation.  Returns None if not found or expired."""
    return await _get_backend().get(conversation_id)


async def save_conversation(state: ConversationState) -> None:
    """Persist the current state (upsert). Resets TTL."""
    await _get_backend().save(state)


async def delete_conversation(conversation_id: str) -> None:
    """Remove a conversation."""
    await _get_backend().delete(conversation_id)
