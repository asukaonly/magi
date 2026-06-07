"""Generic message-dict text helpers (layer-free).

Pure string / message-dict utilities with no agent-internal dependencies.
Lowered out of ``magi.agent.message_utils`` so non-agent layers (e.g. the
context-decider prompt builder under ``magi.tools``) can reuse them without
importing the agent layer. ``magi.agent.message_utils`` re-imports these so
its own callers keep working unchanged.
"""

from __future__ import annotations

from typing import Any


def trim_latest_user_message(
    recent_messages: list[dict[str, Any]] | None,
    latest_user_message: str,
) -> list[dict[str, Any]]:
    """Return recent messages without a trailing copy of the current user message."""
    messages = list(recent_messages or [])
    normalized_latest = str(latest_user_message or "").strip()
    if normalized_latest and _is_matching_user_message(
        messages[-1] if messages else None, normalized_latest
    ):
        return messages[:-1]
    return messages


def _is_matching_user_message(message: dict[str, Any] | None, latest_user_message: str) -> bool:
    if not isinstance(message, dict):
        return False
    return (
        str(message.get("role", "")).strip() == "user"
        and _extract_text_content(message.get("content")) == latest_user_message
    )


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
