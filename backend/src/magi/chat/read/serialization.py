"""Pure serialization helpers for chat read models."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, cast

from ..contracts import ChatMessageLabel, ChatReplyPreview
from .models import ChatDisplayMessage, ChatSessionSummary

_ASSISTANT_MESSAGE_KINDS = {
    "assistant_final",
    "assistant_interim",
    "assistant_reaction",
    "assistant_rhythm_segment",
    "ask_request",
}
_STATUS_MESSAGE_KINDS = {
    "command_result",
    "status_note",
    "system_notice",
    "plan_state",
    "permission_request",
    "background_task_completion",
    "background_task_pending",
}
_USER_PAYLOAD_MESSAGE_KINDS = {"ask_response", "command_invocation"}


@dataclass(slots=True)
class _DisplayRowContext:
    message_kind: str
    content: str
    payload: dict[str, Any]
    attachments: list[dict[str, Any]]
    role: str
    label_payload: dict[str, Any] | None
    turn_id: str | None
    timestamp: int
    message_id: str
    persona_id: str | None


def parse_turn_ux_preferences(raw_ux_plan_json: str | None) -> dict[str, Any]:
    if not raw_ux_plan_json:
        return {}
    try:
        parsed = json.loads(raw_ux_plan_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def apply_turn_ux_preferences(
    message: ChatDisplayMessage,
    preferences: dict[str, Any] | None,
) -> None:
    if not preferences:
        return
    trace_display_mode = preferences.get("trace_display_mode")
    if trace_display_mode is not None:
        message.trace_display_mode = str(trace_display_mode)
    if "allow_trace_collapse" in preferences:
        message.allow_trace_collapse = bool(preferences.get("allow_trace_collapse"))


def row_to_display_message(row: sqlite3.Row) -> ChatDisplayMessage | None:
    context = _build_display_row_context(row)
    if not context.content and not context.attachments:
        return None

    if context.message_kind == "user_text":
        return _build_display_message(
            context,
            role="user",
            kind="user",
            payload_keys=(
                "recall_feedback",
                "interaction_kind",
                "first_context",
                "reasoning_preference",
            ),
        )
    if context.message_kind in _USER_PAYLOAD_MESSAGE_KINDS:
        return _build_display_message(
            context,
            role="user",
            kind="user",
            include_payload=True,
        )
    if context.message_kind in _ASSISTANT_MESSAGE_KINDS:
        return _build_display_message(
            context,
            role=context.role,
            kind="assistant",
            include_payload=True,
        )
    if context.message_kind in _STATUS_MESSAGE_KINDS:
        return _build_display_message(
            context,
            role=context.role,
            kind="status",
            include_payload=True,
            include_attachments=False,
            include_label=context.message_kind not in _BACKGROUND_TASK_MESSAGE_KINDS,
        )
    return None


_BACKGROUND_TASK_MESSAGE_KINDS = {
    "background_task_completion",
    "background_task_pending",
}


def _build_display_row_context(row: sqlite3.Row) -> _DisplayRowContext:
    payload = parse_message_payload_json(row["payload_json"])
    raw_attachments = payload.get("attachments")
    attachments = (
        cast(list[dict[str, Any]], raw_attachments) if isinstance(raw_attachments, list) else []
    )
    label = parse_label_payload(row["label_json"])
    return _DisplayRowContext(
        message_kind=str(row["message_kind"] or ""),
        content=str(row["content_text"] or "").strip(),
        payload=payload,
        attachments=attachments,
        role=str(row["role"] or "assistant"),
        label_payload=label.to_dict() if label is not None else None,
        turn_id=str(row["turn_id"] or "").strip() or None,
        timestamp=int(row["created_at_ms"] or 0),
        message_id=str(row["message_id"]),
        persona_id=_row_persona_id(row),
    )


def _row_persona_id(row: sqlite3.Row) -> str | None:
    if "persona_id" not in row.keys():
        return None
    return str(row["persona_id"] or "").strip() or None


def _build_display_message(
    context: _DisplayRowContext,
    *,
    role: str,
    kind: str,
    include_payload: bool = False,
    payload_keys: tuple[str, ...] = (),
    include_attachments: bool = True,
    include_label: bool = True,
) -> ChatDisplayMessage:
    payload: dict[str, Any] | None = None
    if include_payload:
        payload = dict(context.payload)
    elif payload_keys:
        selected_payload = {
            key: context.payload[key] for key in payload_keys if key in context.payload
        }
        payload = selected_payload or None
    return ChatDisplayMessage(
        role=role,
        kind=kind,
        content=context.content,
        attachments=list(context.attachments) if include_attachments else [],
        timestamp=context.timestamp,
        message_id=context.message_id,
        message_kind=context.message_kind,
        persona_id=context.persona_id,
        turn_id=context.turn_id,
        payload=payload,
        label=context.label_payload if include_label else None,
    )


def build_reply_preview(target_row: sqlite3.Row | None) -> dict[str, Any] | None:
    if target_row is None:
        return None
    content = str(target_row["content_text"] or "").strip()
    return cast(
        dict[str, Any],
        ChatReplyPreview(
            message_id=str(target_row["message_id"]),
            role=str(target_row["role"] or "assistant"),
            message_kind=str(target_row["message_kind"] or "").strip() or None,
            content_excerpt=content[:160],
        ).to_dict(),
    )


def row_to_session_summary(row: sqlite3.Row) -> ChatSessionSummary:
    return ChatSessionSummary(
        session_id=str(row["session_id"]),
        title=str(row["title"] or ""),
        last_message_preview=str(row["last_message_preview"] or ""),
        last_user_message_preview=str(row["last_user_message_preview"] or ""),
        title_overridden=bool(int(row["title_overridden"] or 0)),
        last_timestamp=int(row["last_message_at_ms"] or row["updated_at_ms"] or 0),
        message_count=int(row["message_count"] or 0),
        workspace_path=str(row["workspace_path"]) if row["workspace_path"] is not None else None,
        history_version=(
            int(row["history_version"] or 0) if "history_version" in row.keys() else 0
        ),
    )


def parse_message_payload_json(raw_payload_json: str | None) -> dict[str, Any]:
    if not raw_payload_json:
        return {}
    try:
        parsed = json.loads(raw_payload_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_label_payload(raw_label_json: str | None) -> ChatMessageLabel | None:
    if not raw_label_json:
        return None
    try:
        parsed = json.loads(raw_label_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    kind = str(parsed.get("kind") or "").strip()
    text = str(parsed.get("text") or "").strip()
    applied_by = str(parsed.get("applied_by") or "").strip()
    source = str(parsed.get("source") or "").strip()
    created_at_ms = int(parsed.get("created_at_ms") or 0)
    if not kind or not text or not applied_by or not source or created_at_ms <= 0:
        return None
    return ChatMessageLabel(
        kind=kind,
        text=text,
        applied_by=applied_by,
        source=source,
        created_at_ms=created_at_ms,
    )


def normalize_workspace_path(workspace_path: str | None) -> str | None:
    normalized_workspace_path = str(workspace_path or "").strip()
    return normalized_workspace_path or None
