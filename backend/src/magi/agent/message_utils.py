"""Helpers for assembling chat history passed to LLM calls."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from ..chat import get_chat_read_service

DEFAULT_HISTORY_TOKEN_BUDGET = 96_000
_CHARS_PER_TOKEN_ESTIMATE = 4
_SESSION_CONTEXT_ROLE = "user"


def append_latest_user_message(
    history: list[dict[str, Any]] | None,
    latest_user_message: str,
    *,
    history_limit: int | None = None,
    history_token_budget: int | None = DEFAULT_HISTORY_TOKEN_BUDGET,
    session_summary: str | None = None,
    session_origin: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return prompt history with the current user message appended once.

    When ``history_limit`` is omitted, selection is token-budget based: keep
    as much available session history as fits, preserve a compact session
    origin anchor when the head must be dropped, and reserve room for the
    latest user message.
    """
    source_messages = _normalize_prompt_messages(history or [])
    normalized_latest = str(latest_user_message or "").strip()
    latest_content = _build_latest_user_message_content(
        normalized_latest,
        attachments or [],
        user_id=user_id,
        session_id=session_id,
    )
    # Remove all trailing user messages that match the current message to
    # collapse duplicates caused by retried sends that had no assistant
    # response in between.
    if not attachments:
        while source_messages and _is_matching_user_message(source_messages[-1], normalized_latest):
            source_messages.pop()

    if history_limit is not None:
        safe_history_limit = max(0, history_limit)
        messages = [] if safe_history_limit == 0 else list(source_messages[-safe_history_limit:])
    else:
        messages = _select_history_for_prompt(
            source_messages,
            latest_content=latest_content,
            history_token_budget=history_token_budget,
            session_summary=session_summary,
            session_origin=session_origin,
        )

    if latest_content is None:
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
    if normalized_excluded and _is_matching_user_message(
        source[-1] if source else None, normalized_excluded
    ):
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


def _build_latest_user_message_content(
    latest_user_message: str,
    attachments: list[dict[str, Any]],
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> str | list[dict[str, str]] | None:
    blocks: list[dict[str, str]] = []
    if latest_user_message:
        blocks.append({"type": "text", "text": latest_user_message})

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        kind = str(attachment.get("kind") or "").strip()

        if kind == "mcp_resource":
            resolved_text = attachment.get("resolved_text")
            if isinstance(resolved_text, str) and resolved_text.strip():
                blocks.append({"type": "text", "text": resolved_text})
            continue

        if kind != "image":
            continue
        storage_path = str(attachment.get("storage_path") or "").strip()
        if not storage_path and user_id and session_id:
            attachment_id = str(attachment.get("attachment_id") or "").strip()
            if attachment_id:
                resolved = get_chat_read_service().get_attachment_payload(
                    user_id, session_id, attachment_id
                )
                if isinstance(resolved, dict):
                    storage_path = str(resolved.get("storage_path") or "").strip()
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


def _normalize_prompt_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant", "tool", "tool_result"}:
            continue
        content = item.get("content")
        if _extract_text_content(content) or isinstance(content, list):
            messages.append({"role": role, "content": content})
    return messages


def _select_history_for_prompt(
    history: list[dict[str, Any]],
    *,
    latest_content: str | list[dict[str, str]] | None,
    history_token_budget: int | None,
    session_summary: str | None,
    session_origin: str | None,
) -> list[dict[str, Any]]:
    if not history:
        return _build_session_context_messages(
            session_origin=session_origin,
            session_summary=session_summary,
        )
    if history_token_budget is None or history_token_budget <= 0:
        return [
            *_build_session_context_messages(
                session_origin=session_origin,
                session_summary=session_summary,
            ),
            *history,
        ]

    latest_tokens = (
        _estimate_prompt_message_tokens({"role": "user", "content": latest_content})
        if latest_content
        else 0
    )
    base_context = _build_session_context_messages(
        session_origin=session_origin,
        session_summary=session_summary,
    )
    selected_tail = _select_tail_by_token_budget(
        history,
        max(
            0, history_token_budget - latest_tokens - _estimate_prompt_messages_tokens(base_context)
        ),
    )
    if len(selected_tail) == len(history):
        return [*base_context, *selected_tail]

    origin = session_origin or _derive_session_origin_anchor(history)
    context_with_origin = _build_session_context_messages(
        session_origin=origin,
        session_summary=session_summary,
    )
    selected_tail = _select_tail_by_token_budget(
        history,
        max(
            0,
            history_token_budget
            - latest_tokens
            - _estimate_prompt_messages_tokens(context_with_origin),
        ),
    )
    return [*context_with_origin, *selected_tail]


def _build_session_context_messages(
    *,
    session_origin: str | None,
    session_summary: str | None,
) -> list[dict[str, str]]:
    origin = str(session_origin or "").strip()
    summary = str(session_summary or "").strip()
    if not origin and not summary:
        return []
    sections: list[str] = []
    if origin:
        sections.extend(["# Session Origin", origin])
    if summary:
        if sections:
            sections.append("")
        sections.extend(["# Current Session Summary", summary])
    sections.append("")
    sections.append(
        "Use this session context for continuity. Recent messages below remain the source "
        "of truth for the latest turn."
    )
    return [{"role": _SESSION_CONTEXT_ROLE, "content": "\n".join(sections).strip()}]


def _select_tail_by_token_budget(
    messages: list[dict[str, Any]], token_budget: int
) -> list[dict[str, Any]]:
    if token_budget <= 0:
        return messages[-1:] if messages else []
    selected: list[dict[str, Any]] = []
    total_tokens = 0
    for message in reversed(messages):
        message_tokens = _estimate_prompt_message_tokens(message)
        if selected and total_tokens + message_tokens > token_budget:
            break
        selected.append(message)
        total_tokens += message_tokens
        if total_tokens >= token_budget:
            break
    selected.reverse()
    return selected


def _derive_session_origin_anchor(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages[:6]:
        role = str(message.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = _extract_text_content(message.get("content"))
        if not content:
            continue
        if len(content) > 240:
            content = content[:240].rstrip() + "..."
        label = "User" if role == "user" else "Assistant"
        lines.append(f"- {label}: {content}")
        if len(lines) >= 3:
            break
    if not lines:
        return "This session has earlier messages that were omitted from the raw recent tail."
    return "The session began with these early exchanges:\n" + "\n".join(lines)


def _estimate_prompt_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(_estimate_prompt_message_tokens(message) for message in messages)


def _estimate_prompt_message_tokens(message: dict[str, Any]) -> int:
    try:
        rendered = json.dumps(message, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(message)
    return max(1, len(rendered) // _CHARS_PER_TOKEN_ESTIMATE)
