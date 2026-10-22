"""Typed chat session records shared by memory and conversation queries."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class ChatSessionRecord:
    """Canonical chat session row."""

    session_id: str
    user_id: str
    title: str
    title_overridden: bool
    summary: str
    created_at: float
    updated_at: float
    last_message_at: float | None
    last_user_message_at: float | None
    last_message_preview: str
    last_user_message_preview: str
    message_count: int
    archived_at: float | None
    deleted_at: float | None
    workspace_path: str | None = None


def create_chat_session_record(
    *,
    user_id: str,
    session_id: str | None = None,
    title: str = "",
    summary: str = "",
    workspace_path: str | None = None,
    now: float | None = None,
) -> ChatSessionRecord:
    """Build a new canonical chat session row."""

    timestamp = float(now if now is not None else time.time())
    normalized_session_id = str(session_id or "").strip() or str(uuid.uuid4())
    return ChatSessionRecord(
        session_id=normalized_session_id,
        user_id=str(user_id).strip(),
        title=str(title).strip(),
        title_overridden=False,
        summary=str(summary),
        created_at=timestamp,
        updated_at=timestamp,
        last_message_at=None,
        last_user_message_at=None,
        last_message_preview="",
        last_user_message_preview="",
        message_count=0,
        workspace_path=workspace_path,
        archived_at=None,
        deleted_at=None,
    )
