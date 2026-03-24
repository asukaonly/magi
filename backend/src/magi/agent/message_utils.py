"""Helpers for assembling chat history passed to LLM calls."""

from __future__ import annotations

from typing import Any


def append_latest_user_message(
    history: list[dict[str, Any]] | None,
    latest_user_message: str,
    *,
    history_limit: int,
) -> list[dict[str, Any]]:
    """Return recent history with the current user message appended once."""
    messages = list((history or [])[-history_limit:])
    normalized_latest = str(latest_user_message or "").strip()
    if not normalized_latest:
        return messages
    if _is_matching_user_message(messages[-1] if messages else None, normalized_latest):
        return messages
    messages.append({"role": "user", "content": normalized_latest})
    return messages


def build_recent_messages(
    history: list[dict[str, Any]] | None,
    *,
    limit: int,
    content_limit: int,
    exclude_latest_user_message: str | None = None,
) -> list[dict[str, str]]:
    """Return trimmed recent messages suitable for lightweight routing prompts."""
    recent_messages: list[dict[str, str]] = []
    normalized_excluded = str(exclude_latest_user_message or "").strip()
    source = list((history or [])[-limit:])
    if normalized_excluded and _is_matching_user_message(source[-1] if source else None, normalized_excluded):
        source = source[:-1]
    for msg in source:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "unknown")).strip()
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if len(content) > content_limit:
            content = content[:content_limit] + "..."
        recent_messages.append({"role": role, "content": content})
    return recent_messages


def trim_latest_user_message(
    recent_messages: list[dict[str, Any]] | None,
    latest_user_message: str,
) -> list[dict[str, Any]]:
    """Return recent messages without a trailing copy of the current user message."""
    messages = list(recent_messages or [])
    normalized_latest = str(latest_user_message or "").strip()
    if normalized_latest and _is_matching_user_message(messages[-1] if messages else None, normalized_latest):
        return messages[:-1]
    return messages


def _is_matching_user_message(message: dict[str, Any] | None, latest_user_message: str) -> bool:
    if not isinstance(message, dict):
        return False
    return (
        str(message.get("role", "")).strip() == "user"
        and str(message.get("content", "")).strip() == latest_user_message
    )
