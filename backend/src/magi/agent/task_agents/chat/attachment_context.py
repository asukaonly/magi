"""Helpers for resolving chat attachment context for a turn."""
from __future__ import annotations

from typing import Any, Callable

from ....chat import get_chat_read_service


def resolve_effective_turn_attachments(
    context: object,
    *,
    read_service_factory: Callable[[], Any] | None = get_chat_read_service,
) -> list[dict[str, Any]]:
    """Return attachments directly on the current turn plus explicit reply-target attachments."""

    attachments: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def append_items(items: Any, *, resolve_managed_payload: bool = False) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            if resolve_managed_payload:
                normalized = _resolve_managed_attachment_payload(
                    context,
                    normalized,
                    read_service_factory=read_service_factory,
                )
            attachment_id = str(normalized.get("attachment_id") or "").strip()
            if attachment_id:
                if attachment_id in seen_ids:
                    continue
                seen_ids.add(attachment_id)
            attachments.append(normalized)

    latest_payload = getattr(context, "latest_payload", None)
    append_items(getattr(latest_payload, "attachments", []) if latest_payload is not None else [])

    reply_context = getattr(context, "reply_context", None)
    if bool(getattr(reply_context, "is_explicit_reply", False)):
        structured_payload = getattr(reply_context, "structured_payload", None)
        if isinstance(structured_payload, dict):
            append_items(structured_payload.get("attachments"), resolve_managed_payload=True)

    return attachments


def _resolve_managed_attachment_payload(
    context: object,
    attachment: dict[str, Any],
    *,
    read_service_factory: Callable[[], Any] | None,
) -> dict[str, Any]:
    attachment_id = str(attachment.get("attachment_id") or "").strip()
    if not attachment_id or read_service_factory is None:
        return attachment
    user_id = _context_value(context, "user_id")
    session_id = _context_value(context, "session_id")
    if not user_id or not session_id:
        latest_payload = getattr(context, "latest_payload", None)
        user_id = user_id or _context_value(latest_payload, "user_id")
        session_id = session_id or _context_value(latest_payload, "session_id")
    if not user_id or not session_id:
        return attachment
    try:
        resolved = read_service_factory().get_attachment_payload(user_id, session_id, attachment_id)
    except (RuntimeError, ValueError):
        return attachment
    if not isinstance(resolved, dict):
        return attachment
    merged = dict(resolved)
    for key, value in attachment.items():
        if value is not None:
            merged.setdefault(key, value)
    return merged


def _context_value(context: object | None, field_name: str) -> str:
    if context is None:
        return ""
    return str(getattr(context, field_name, "") or "").strip()
