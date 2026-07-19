"""Pure serialization helpers for chat store records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import aiosqlite

from ...utils.runtime import RuntimePaths, get_runtime_paths
from magi.core.chat_assets.paths import (
    build_chat_derived_path,
    is_safe_chat_asset_component,
    resolve_chat_attachment_file,
    resolve_chat_derived_file,
    verified_chat_resources_dir,
)
from ..contracts import ChatMessageLabel, ChatMessageRecord

ChatAssetKind = Literal["attachment", "derived_text"]


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


def managed_chat_asset_reference(
    storage_path: object,
    *,
    runtime_paths: RuntimePaths | None = None,
) -> tuple[str, str] | None:
    """Return the canonical key and base-relative path for one chat asset."""
    normalized = str(storage_path or "").strip()
    if not normalized:
        return None
    paths = runtime_paths or get_runtime_paths()
    base_dir = paths.base_dir.resolve()
    try:
        resources_dir = verified_chat_resources_dir(paths)
    except ValueError:
        return None
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        parent = candidate.parent.resolve()
        parent.relative_to(resources_dir)
        target = parent / candidate.name
        if target.is_symlink():
            return None
        asset_key = target.relative_to(resources_dir).as_posix()
        relative_path = target.relative_to(base_dir).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    return asset_key, relative_path


def message_attachment_storage_reference(
    storage_path: object,
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    runtime_paths: RuntimePaths | None = None,
) -> tuple[str, str] | None:
    """Resolve one original attachment inside its owning message turn."""

    paths = runtime_paths or get_runtime_paths()
    resolved = resolve_chat_attachment_file(
        storage_path,
        session_id=session_id,
        turn_id=turn_id,
        attachment_id=attachment_id,
        runtime_paths=paths,
    )
    if resolved is None:
        return None
    return managed_chat_asset_reference(resolved, runtime_paths=paths)


def message_asset_references(
    attachment_payloads: list[dict[str, object]] | None,
    *,
    session_id: str,
    turn_id: str | None,
    runtime_paths: RuntimePaths | None = None,
) -> tuple[tuple[str, str, ChatAssetKind], ...]:
    """Resolve every original and derived file owned by one message."""
    unique: dict[str, tuple[str, ChatAssetKind]] = {}
    paths = runtime_paths or get_runtime_paths()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    for attachment in attachment_payloads or []:
        if not isinstance(attachment, dict):
            continue
        attachment_id = str(attachment.get("attachment_id") or "").strip()
        if (
            not is_safe_chat_asset_component(attachment_id)
            or not is_safe_chat_asset_component(normalized_session_id)
            or not is_safe_chat_asset_component(normalized_turn_id)
        ):
            continue
        original_reference = message_attachment_storage_reference(
            attachment.get("storage_path"),
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            attachment_id=attachment_id,
            runtime_paths=paths,
        )
        if original_reference is not None:
            asset_key, relative_path = original_reference
            unique.setdefault(asset_key, (relative_path, "attachment"))
        derived_path = resolve_chat_derived_file(
            attachment.get("derived_text_path"),
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            attachment_id=attachment_id,
            runtime_paths=paths,
        )
        if derived_path is not None:
            reference = managed_chat_asset_reference(
                derived_path,
                runtime_paths=paths,
            )
            if reference is not None:
                asset_key, relative_path = reference
                unique.setdefault(asset_key, (relative_path, "derived_text"))
        inferred_path = build_chat_derived_path(
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            attachment_id=attachment_id,
            runtime_paths=paths,
        )
        inferred_reference = managed_chat_asset_reference(
            inferred_path,
            runtime_paths=paths,
        )
        if inferred_reference is not None:
            asset_key, relative_path = inferred_reference
            unique.setdefault(asset_key, (relative_path, "derived_text"))
    return tuple(
        (asset_key, relative_path, asset_kind)
        for asset_key, (relative_path, asset_kind) in unique.items()
    )


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
