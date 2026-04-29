"""Pure serialization helpers for chat read models."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..contracts import ChatMessageLabel, ChatReplyPreview
from .models import ChatDisplayMessage, ChatSessionSummary


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
    message_kind = str(row["message_kind"] or "")
    content = str(row["content_text"] or "").strip()
    payload = parse_message_payload_json(row["payload_json"])
    attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
    if not content and not attachments:
        return None

    role = str(row["role"] or "assistant")
    label = parse_label_payload(row["label_json"])
    label_payload = label.to_dict() if label is not None else None
    turn_id = str(row["turn_id"] or "").strip() or None
    timestamp = int(row["created_at_ms"] or 0)
    message_id = str(row["message_id"])

    if message_kind == "user_text":
        return ChatDisplayMessage(
            role="user",
            kind="user",
            content=content,
            attachments=list(attachments),
            timestamp=timestamp,
            message_id=message_id,
            message_kind=message_kind,
            turn_id=turn_id,
            label=label_payload,
        )
    if message_kind in {"assistant_final", "assistant_interim", "assistant_reaction"}:
        return ChatDisplayMessage(
            role=role,
            kind="assistant",
            content=content,
            attachments=list(attachments),
            timestamp=timestamp,
            message_id=message_id,
            message_kind=message_kind,
            turn_id=turn_id,
            label=label_payload,
        )
    if message_kind in {
        "status_note",
        "system_notice",
        "plan_state",
        "todo_state",
        "permission_request",
        "ask_request",
    }:
        return ChatDisplayMessage(
            role=role,
            kind="status",
            content=content,
            timestamp=timestamp,
            message_id=message_id,
            message_kind=message_kind,
            turn_id=turn_id,
            payload=dict(payload) if isinstance(payload, dict) else None,
            label=label_payload,
        )
    if message_kind == "background_task_completion":
        return ChatDisplayMessage(
            role=role,
            kind="status",
            content=content,
            timestamp=timestamp,
            message_id=message_id,
            message_kind=message_kind,
            turn_id=turn_id,
            payload=dict(payload) if isinstance(payload, dict) else None,
        )
    return None


def build_reply_preview(target_row: sqlite3.Row | None) -> dict[str, Any] | None:
    if target_row is None:
        return None
    content = str(target_row["content_text"] or "").strip()
    return ChatReplyPreview(
        message_id=str(target_row["message_id"]),
        role=str(target_row["role"] or "assistant"),
        message_kind=str(target_row["message_kind"] or "").strip() or None,
        content_excerpt=content[:160],
    ).to_dict()


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
