"""Pure serialization helpers for chat store records."""

from __future__ import annotations

from magi_plugin_sdk.storage_chat.relational import ChatRow

import json
from pathlib import Path
from typing import Literal


from magi_plugin_sdk.storage_models.chat import ChatMessageLabel, ChatMessageRecord

ChatAssetKind = Literal["attachment", "derived_text"]


def _coerce_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default








def row_to_message(row: ChatRow) -> ChatMessageRecord:
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
