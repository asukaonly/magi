"""Canonical chat session storage helpers."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import aiosqlite

CHAT_SESSIONS_TABLE = "chat_sessions"


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


async def project_chat_event_to_session(
    db: aiosqlite.Connection,
    *,
    user_id: str | None,
    session_id: str | None,
    event_type: str,
    content: str | None,
    timestamp: float,
) -> None:
    """Project chat fact activity into the canonical session row."""

    normalized_user_id = str(user_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_content = str(content or "").strip()
    if not normalized_user_id or not normalized_session_id or not normalized_content:
        return

    await db.execute(
        f"""
        INSERT INTO {CHAT_SESSIONS_TABLE} (
            session_id, user_id, title, title_overridden, summary, created_at, updated_at,
            last_message_at, last_user_message_at, last_message_preview,
            last_user_message_preview, message_count, workspace_path, archived_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO NOTHING
        """,
        (
            normalized_session_id,
            normalized_user_id,
            "",
            0,
            "",
            float(timestamp),
            float(timestamp),
            None,
            None,
            "",
            "",
            0,
            None,
            None,
            None,
        ),
    )
    if event_type == "UserMessage":
        await db.execute(
            f"""
            UPDATE {CHAT_SESSIONS_TABLE}
            SET
                updated_at = ?,
                last_message_at = ?,
                last_user_message_at = ?,
                last_message_preview = ?,
                last_user_message_preview = ?,
                message_count = message_count + 1
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at IS NULL
            """,
            (
                float(timestamp),
                float(timestamp),
                float(timestamp),
                normalized_content[:120],
                normalized_content[:120],
                normalized_session_id,
                normalized_user_id,
            ),
        )
        return

    if event_type == "AIResponse":
        await db.execute(
            f"""
            UPDATE {CHAT_SESSIONS_TABLE}
            SET
                updated_at = ?,
                last_message_at = ?,
                last_message_preview = ?,
                message_count = message_count + 1
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at IS NULL
            """,
            (
                float(timestamp),
                float(timestamp),
                normalized_content[:120],
                normalized_session_id,
                normalized_user_id,
            ),
        )
