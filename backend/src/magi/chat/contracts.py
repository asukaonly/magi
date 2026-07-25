"""Typed contracts for the dedicated chat domain store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CHAT_DELIVERY_STATE_READY = "ready"
CHAT_DELIVERY_STATE_QUEUED = "queued"
CHAT_DELIVERY_STATE_ADMITTED = "admitted"
CHAT_DELIVERY_STATE_TERMINAL = "terminal"
CHAT_DELIVERY_STATES = frozenset(
    {
        CHAT_DELIVERY_STATE_READY,
        CHAT_DELIVERY_STATE_QUEUED,
        CHAT_DELIVERY_STATE_ADMITTED,
        CHAT_DELIVERY_STATE_TERMINAL,
    }
)
CHAT_RECOVERABLE_DELIVERY_STATES = frozenset(
    {
        CHAT_DELIVERY_STATE_READY,
        CHAT_DELIVERY_STATE_QUEUED,
        CHAT_DELIVERY_STATE_ADMITTED,
    }
)


@dataclass(slots=True)
class ChatSessionRecord:
    """Durable chat session metadata."""

    session_id: str
    user_id: str
    title: str
    title_overridden: bool
    summary: str
    created_at_ms: int
    updated_at_ms: int
    last_message_at_ms: int | None
    last_user_message_at_ms: int | None
    last_message_preview: str
    last_user_message_preview: str
    message_count: int
    archived_at_ms: int | None
    deleted_at_ms: int | None
    workspace_path: str | None = None
    history_version: int = 0


@dataclass(slots=True)
class ChatTurnRecord:
    """Durable per-turn state."""

    turn_id: str
    session_id: str
    user_id: str
    trace_id: str | None
    orchestration_id: str | None
    status: str
    response_mode: str
    execution_mode: str | None
    ux_plan_json: str
    created_at_ms: int
    updated_at_ms: int
    completed_at_ms: int | None
    error_text: str | None
    run_id: str | None = None
    run_revision: int = 0
    run_disposition: str | None = None
    response_anchor_turn_id: str | None = None
    superseded_by_turn_id: str | None = None
    supersession_reason: str | None = None


@dataclass(slots=True)
class ChatMessageRecord:
    """Durable transcript message row."""

    message_id: str
    session_id: str
    turn_id: str | None
    user_id: str
    role: str
    message_kind: str
    content_text: str | None
    payload_json: str
    is_final: bool
    is_visible: bool
    created_at_ms: int
    sequence_no: int
    replaces_message_id: str | None
    replaced_by_message_id: str | None
    persona_id: str | None = None
    reply_to_message_id: str | None = None
    label: "ChatMessageLabel | None" = None


@dataclass(frozen=True, slots=True)
class ChatAssistantMemoryProjection:
    """Canonical assistant message waiting for durable L1 confirmation."""

    canonical_message_id: str
    user_id: str
    session_id: str
    turn_id: str
    content: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ChatAssistantMemoryOutboxRecord:
    """One leased assistant-memory projection outbox row."""

    projection: ChatAssistantMemoryProjection
    attempt_count: int
    lease_token: str
    lease_expires_at_ms: int


@dataclass(slots=True)
class CreateUserTurnResult:
    """Result of an idempotent user-turn creation attempt."""

    message: ChatMessageRecord
    created: bool
    projection_completed: bool
    delivery_attempt_no: int
    delivery_state: str
    current_command_id: int | None
    runtime_envelope: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatUserTurnDeliveryRecord:
    """Durable runtime-delivery state for one accepted user turn."""

    user_id: str
    session_id: str
    turn_id: str
    message_id: str
    projection_completed: bool
    delivery_attempt_no: int
    delivery_state: str
    current_command_id: int | None
    runtime_envelope: dict[str, Any]
    request_fingerprint: str
    created_at_ms: int
    sequence_no: int


@dataclass(slots=True)
class ChatContextSummaryRecord:
    """Durable rolling summary for one chat session prompt frontier."""

    summary_id: str
    session_id: str
    parent_summary_id: str | None
    status: str
    summary_kind: str
    persona_scope: str | None
    covered_from_message_id: str | None
    covered_to_message_id: str | None
    first_kept_message_id: str | None
    covered_to_sequence_no: int | None
    session_origin: str
    summary_text: str
    prompt_profile: str
    model_provider: str | None
    model_id: str | None
    token_count_before: int | None
    token_count_after: int | None
    quality_status: str | None
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class ChatContextUsageSnapshot:
    """Durable provider-input usage for one accepted visible assistant turn."""

    turn_id: str
    session_id: str
    user_id: str
    used_tokens: int
    context_window: int
    input_capacity: int
    compaction_threshold: int
    measurement: str
    model_provider: str | None
    model_id: str | None
    updated_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "used_tokens": self.used_tokens,
            "window_size": self.context_window,
            "input_capacity": self.input_capacity,
            "threshold": self.compaction_threshold,
            "measurement": self.measurement,
            "model_provider": self.model_provider,
            "model_id": self.model_id,
            "updated_at_ms": self.updated_at_ms,
        }


@dataclass(slots=True)
class ChatReplyPreview:
    """Compact display preview for one replied-to message."""

    message_id: str
    role: str
    message_kind: str | None
    content_excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "message_kind": self.message_kind,
            "content_excerpt": self.content_excerpt,
        }


@dataclass(slots=True)
class ChatMessageLabel:
    """Compact durable label attached to one message."""

    kind: str
    text: str
    applied_by: str
    source: str
    created_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "applied_by": self.applied_by,
            "source": self.source,
            "created_at_ms": self.created_at_ms,
        }
