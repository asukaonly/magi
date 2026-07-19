"""Helpers for assembling chat history passed to LLM calls."""

from __future__ import annotations

import base64
from typing import Any

from magi.core.chat_assets.io import open_managed_chat_attachment
from magi.context.window_budget import estimate_context_tokens

from .run.ports import AttachmentResolverPort
from .turn_input import UserTurnInput
from ..utils.message_text import (
    _extract_text_content,
    _is_matching_user_message,
)

_SESSION_CONTEXT_ROLE = "user"


def append_latest_user_message(
    history: list[dict[str, Any]] | None,
    turn: UserTurnInput,
    *,
    resolver: AttachmentResolverPort,
    history_token_budget: int | None,
    history_limit: int | None = None,
    session_summary: str | None = None,
    session_origin: str | None = None,
    reply_context: Any | None = None,
) -> list[dict[str, Any]]:
    """Return prompt history with the current user turn appended once.

    The ``turn`` carries text + attachments together so callers cannot drop
    one without dropping the other. When ``history_limit`` is omitted,
    selection is token-budget based.

    ``resolver`` resolves managed attachment payloads (e.g. an image whose
    ``storage_path`` is not embedded in the turn). Chat injects a chat-backed
    resolver; non-chat callers inject ``NullAttachmentResolver``.
    """
    source_messages = _normalize_prompt_messages(history or [])
    normalized_latest = str(turn.text or "").strip()
    latest_content = _build_latest_user_message_content(
        normalized_latest,
        list(turn.attachments or []),
        resolver=resolver,
        user_id=turn.user_id,
        session_id=turn.session_id,
        reply_context=reply_context,
    )
    # The durable history can already include the current turn before the
    # runtime command is processed. Keep the richer latest turn below, which
    # may include model-visible attachments, and remove matching text copies.
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


def group_prompt_history_turns(
    messages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group normalized prompt history into atomic user-led exchanges."""
    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = []
    for message in _normalize_prompt_messages(messages):
        if message.get("role") == "user" and current_group:
            groups.append(current_group)
            current_group = []
        current_group.append(message)
    if current_group:
        groups.append(current_group)
    return groups


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


def _build_latest_user_message_content(
    latest_user_message: str,
    attachments: list[dict[str, Any]],
    *,
    resolver: AttachmentResolverPort,
    user_id: str | None = None,
    session_id: str | None = None,
    reply_context: Any | None = None,
) -> str | list[dict[str, str]] | None:
    blocks: list[dict[str, str]] = []
    if latest_user_message:
        blocks.append({"type": "text", "text": latest_user_message})

    reply_context_note = _build_reply_context_note(reply_context)
    if reply_context_note:
        blocks.append({"type": "text", "text": reply_context_note})

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
        resolved_attachment = attachment
        storage_path = str(attachment.get("storage_path") or "").strip()
        if not storage_path and user_id and session_id:
            attachment_id = str(attachment.get("attachment_id") or "").strip()
            if attachment_id:
                resolved = resolver.get_attachment_payload(user_id, session_id, attachment_id)
                if isinstance(resolved, dict):
                    resolved_attachment = resolved
                    storage_path = str(resolved.get("storage_path") or "").strip()
        if not storage_path:
            continue
        handle = open_managed_chat_attachment(
            storage_path,
            session_id=session_id,
            turn_id=resolved_attachment.get("turn_id"),
            attachment_id=resolved_attachment.get("attachment_id")
            or attachment.get("attachment_id"),
            original_name=resolved_attachment.get("original_name")
            or attachment.get("original_name"),
        )
        if handle is None:
            continue
        mime_type = str(attachment.get("mime_type") or "image/png").strip() or "image/png"
        with handle:
            image_bytes = handle.read()
        blocks.append(
            {
                "type": "image",
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("ascii"),
            }
        )

    if not blocks:
        return None
    if all(block.get("type") == "text" for block in blocks):
        text_blocks = [
            str(block.get("text") or "").strip()
            for block in blocks
            if str(block.get("text") or "").strip()
        ]
        return "\n\n".join(text_blocks)
    return blocks


def _build_reply_context_note(reply_context: Any | None) -> str:
    if reply_context is None or not bool(getattr(reply_context, "is_explicit_reply", False)):
        return ""
    lines = ["[Current message reply target]"]
    message_id = str(getattr(reply_context, "message_id", "") or "").strip()
    if message_id:
        lines.append(f"message_id={message_id}")
    role = str(getattr(reply_context, "role", "") or "").strip()
    if role:
        lines.append(f"speaker={role}")
    content_excerpt = str(getattr(reply_context, "content_excerpt", "") or "").strip()
    if content_excerpt:
        lines.append(f'message="{content_excerpt}"')
    structured_payload = getattr(reply_context, "structured_payload", None)
    attachments = (
        structured_payload.get("attachments") if isinstance(structured_payload, dict) else None
    )
    if isinstance(attachments, list) and attachments:
        lines.append("Referenced attachments from the replied-to message:")
        for attachment in attachments[:6]:
            if not isinstance(attachment, dict):
                continue
            attachment_id = str(attachment.get("attachment_id") or "").strip()
            if not attachment_id:
                continue
            name = str(attachment.get("original_name") or "attachment").strip() or "attachment"
            kind = str(attachment.get("kind") or "file").strip() or "file"
            details = [
                f"attachment_id={attachment_id}",
                f"name={name}",
                f"kind={kind}",
            ]
            mime_type = str(attachment.get("mime_type") or "").strip()
            if mime_type:
                details.append(f"mime_type={mime_type}")
            page_count = attachment.get("page_count")
            if isinstance(page_count, int):
                details.append(f"pages={page_count}")
            character_count = attachment.get("character_count")
            if isinstance(character_count, int):
                details.append(f"chars={character_count}")
            parse_status = str(attachment.get("parse_status") or "").strip()
            if parse_status:
                details.append(f"parse_status={parse_status}")
            lines.append("- " + "; ".join(details))
        lines.append(
            "Interpret deictic phrases like this image, that document, or the previous attachment against this reply target first."
        )
    return "\n".join(lines).strip()


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
    return estimate_context_tokens(message)
