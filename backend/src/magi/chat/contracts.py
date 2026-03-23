"""Typed contracts for the dedicated chat domain store."""

from __future__ import annotations

from dataclasses import dataclass


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
