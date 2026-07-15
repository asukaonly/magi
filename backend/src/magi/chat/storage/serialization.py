"""Pure serialization helpers for chat store records."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from ...utils.runtime import get_runtime_paths
from ..contracts import ChatMessageLabel, ChatMessageRecord


def _coerce_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def build_user_message_payload_json(
    attachment_payloads: list[dict[str, object]] | None,
    message_payload: dict[str, object] | None = None,
) -> str:
    payload = dict(message_payload or {})
    public_attachments = public_attachment_payloads(attachment_payloads)
    if public_attachments:
        payload["attachments"] = public_attachments
    if not payload:
        return "{}"
    return json.dumps(payload, ensure_ascii=False)


def extract_attachment_payloads(raw_payload_json: str | None) -> list[dict[str, object]]:
    if not raw_payload_json:
        return []
    try:
        payload = json.loads(raw_payload_json)
    except (json.JSONDecodeError, TypeError):
        return []
    attachments = payload.get("attachments") if isinstance(payload, dict) else None
    if not isinstance(attachments, list):
        return []
    return [dict(item) for item in attachments if isinstance(item, dict)]


def public_attachment_payloads(
    attachment_payloads: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    if not attachment_payloads:
        return []
    allowed_keys = {
        "attachment_id",
        "kind",
        "original_name",
        "mime_type",
        "size_bytes",
        "parse_status",
        "derived_text_excerpt",
        "character_count",
        "truncated",
        "encoding",
        "page_count",
        "parse_error",
        # MCP resource attachments — references plus pre-read content.
        "server_id",
        "uri",
        "resolved_text",
        "resolved_error",
    }
    public_payloads: list[dict[str, object]] = []
    for item in attachment_payloads:
        if not isinstance(item, dict):
            continue
        public_payload = {
            key: value for key, value in item.items() if key in allowed_keys and value is not None
        }
        if public_payload:
            public_payloads.append(public_payload)
    return public_payloads


def storage_rel_path(storage_path: str) -> str | None:
    candidate = Path(str(storage_path or "").strip())
    if not str(candidate).strip():
        return None
    try:
        base_dir = get_runtime_paths().base_dir.resolve()
        relative = candidate.resolve().relative_to(base_dir)
    except Exception:
        return None
    return relative.as_posix()


def row_to_message(row: aiosqlite.Row) -> ChatMessageRecord:
    return ChatMessageRecord(
        message_id=str(row["message_id"]),
        session_id=str(row["session_id"]),
        turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
        user_id=str(row["user_id"]),
        role=str(row["role"]),
        message_kind=str(row["message_kind"]),
        content_text=str(row["content_text"]) if row["content_text"] is not None else None,
        payload_json=str(row["payload_json"]),
        is_final=bool(int(row["is_final"])),
        is_visible=bool(int(row["is_visible"])),
        created_at_ms=int(row["created_at_ms"]),
        sequence_no=int(row["sequence_no"]),
        replaces_message_id=str(row["replaces_message_id"])
        if row["replaces_message_id"] is not None
        else None,
        replaced_by_message_id=str(row["replaced_by_message_id"])
        if row["replaced_by_message_id"] is not None
        else None,
        persona_id=(
            str(row["persona_id"])
            if "persona_id" in row.keys() and row["persona_id"] is not None
            else None
        ),
        reply_to_message_id=(
            str(row["reply_to_message_id"]) if row["reply_to_message_id"] is not None else None
        ),
        label=parse_message_label(row["label_json"] if "label_json" in row.keys() else None),
    )


def normalize_message_label(
    label: dict[str, object] | ChatMessageLabel | None,
) -> ChatMessageLabel | None:
    if label is None:
        return None
    if isinstance(label, ChatMessageLabel):
        return label
    kind = str(label.get("kind") or "").strip()
    text = str(label.get("text") or "").strip()
    applied_by = str(label.get("applied_by") or "").strip()
    source = str(label.get("source") or "").strip()
    created_at_ms = _coerce_int(label.get("created_at_ms"))
    if not kind or not text or not applied_by or not source or created_at_ms <= 0:
        return None
    return ChatMessageLabel(
        kind=kind,
        text=text,
        applied_by=applied_by,
        source=source,
        created_at_ms=created_at_ms,
    )


def serialize_message_label(label: ChatMessageLabel | None) -> str | None:
    if label is None:
        return None
    return json.dumps(label.to_dict(), ensure_ascii=False)


def parse_message_label(raw_label_json: object) -> ChatMessageLabel | None:
    if raw_label_json is None:
        return None
    raw_text = str(raw_label_json or "").strip()
    if not raw_text:
        return None
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return normalize_message_label(parsed)
