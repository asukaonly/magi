"""Helpers for assembling chat history passed to LLM calls."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


def append_latest_user_message(
    history: list[dict[str, Any]] | None,
    latest_user_message: str,
    *,
    history_limit: int,
    attachments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return recent history with the current user message appended once."""
    messages = list((history or [])[-history_limit:])
    normalized_latest = str(latest_user_message or "").strip()
    latest_content = _build_latest_user_message_content(normalized_latest, attachments or [])
    if latest_content is None:
        return messages
    if not attachments and _is_matching_user_message(messages[-1] if messages else None, normalized_latest):
        return messages
    messages.append({"role": "user", "content": latest_content})
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
        content = _extract_text_content(msg.get("content"))
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
        and _extract_text_content(message.get("content")) == latest_user_message
    )


def _build_latest_user_message_content(
    latest_user_message: str,
    attachments: list[dict[str, Any]],
) -> str | list[dict[str, str]] | None:
    blocks: list[dict[str, str]] = []
    if latest_user_message:
        blocks.append({"type": "text", "text": latest_user_message})

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if str(attachment.get("kind") or "").strip() != "image":
            continue
        storage_path = str(attachment.get("storage_path") or "").strip()
        if not storage_path:
            continue
        path = Path(storage_path)
        if not path.is_file():
            continue
        mime_type = str(attachment.get("mime_type") or "image/png").strip() or "image/png"
        blocks.append(
            {
                "type": "image",
                "mime_type": mime_type,
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
        )

    if not blocks:
        return None
    if len(blocks) == 1 and blocks[0]["type"] == "text":
        return blocks[0]["text"]
    return blocks


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "").strip() != "text":
                continue
            text_value = str(block.get("text") or "").strip()
            if text_value:
                text_parts.append(text_value)
        return "\n".join(text_parts).strip()
    return str(content or "").strip()
