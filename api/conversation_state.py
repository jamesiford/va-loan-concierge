"""
In-memory conversation state for human-in-the-loop flows.

Tracks multi-turn conversations where the orchestrator pauses to collect
user input (e.g., missing profile info, appointment confirmation).

State is ephemeral — lost on server restart. Acceptable for a demo;
production would use Redis or Cosmos DB.
"""

import time
import uuid
from dataclasses import dataclass, field

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
# In-memory store
# ---------------------------------------------------------------------------

_store: dict[str, ConversationState] = {}


def create_conversation(
    profile_id: str | None = None,
    original_query: str = "",
) -> ConversationState:
    """Create a new conversation and return its state."""
    _cleanup_expired()
    state = ConversationState(
        conversation_id=uuid.uuid4().hex[:12],
        profile_id=profile_id,
        original_query=original_query,
    )
    _store[state.conversation_id] = state
    return state


def get_conversation(conversation_id: str) -> ConversationState | None:
    """Look up a conversation. Returns None if not found or expired."""
    state = _store.get(conversation_id)
    if state is None:
        return None
    if state.is_expired:
        _store.pop(conversation_id, None)
        return None
    state.touch()
    return state


def delete_conversation(conversation_id: str) -> None:
    _store.pop(conversation_id, None)


def _cleanup_expired() -> None:
    """Lazily remove expired entries on each new conversation."""
    expired = [k for k, v in _store.items() if v.is_expired]
    for k in expired:
        del _store[k]
