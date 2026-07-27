"""Display helpers for L0 memory session list responses."""
from __future__ import annotations

import re
from typing import Any


def short_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not normalized:
        return ""
    if "-" in normalized:
        return normalized.split("-", 1)[0]
    return normalized[:8]


def truncate_session_preview(value: str, *, limit: int = 72) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def is_generic_chat_title(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"", "new chat", "new session", "新对话", "新会话"}


def derive_l0_session_display(
    *,
    session_id: str,
    attention_items: list[dict[str, Any]],
    chat_summary: Any = None,
) -> dict[str, str | None]:
    session_short_id = short_session_id(session_id)
    attention_title = ""
    if attention_items:
        first_item = attention_items[0]
        attention_title = truncate_session_preview(
            str(first_item.get("summary") or "")
        )

    chat_title = truncate_session_preview(str(getattr(chat_summary, "title", "") or ""))
    user_preview = truncate_session_preview(str(getattr(chat_summary, "last_user_message_preview", "") or ""))
    last_preview = truncate_session_preview(str(getattr(chat_summary, "last_message_preview", "") or ""))
    workspace_path = str(getattr(chat_summary, "workspace_path", "") or "").strip()
    workspace_name = workspace_path.rstrip("/").split("/")[-1] if workspace_path else ""

    display_title = (
        (chat_title if not is_generic_chat_title(chat_title) else "")
        or attention_title
        or user_preview
        or last_preview
        or session_short_id
        or session_id
    )

    display_subtitle = None
    for candidate in (user_preview, last_preview, workspace_name):
        if candidate and candidate != display_title:
            display_subtitle = candidate
            break

    return {
        "short_session_id": session_short_id or session_id,
        "display_title": display_title,
        "display_subtitle": display_subtitle,
    }
