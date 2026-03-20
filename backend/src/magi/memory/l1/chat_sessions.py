"""Canonical chat session storage helpers."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import aiosqlite

CHAT_SESSIONS_TABLE = "chat_sessions"

CHAT_SESSIONS_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {CHAT_SESSIONS_TABLE} (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_message_at REAL,
    last_user_message_at REAL,
    last_message_preview TEXT NOT NULL DEFAULT '',
    last_user_message_preview TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    archived_at REAL,
    deleted_at REAL
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
    ON {CHAT_SESSIONS_TABLE}(user_id, deleted_at, archived_at, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_last_message
    ON {CHAT_SESSIONS_TABLE}(user_id, last_message_at DESC);
"""


@dataclass(slots=True)
class ChatSessionRecord:
    """Canonical chat session row."""

    session_id: str
    user_id: str
    title: str
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


async def ensure_chat_sessions_schema_async(db: aiosqlite.Connection) -> None:
    """Create the canonical chat session schema for an async connection."""

    await db.executescript(CHAT_SESSIONS_SCHEMA_SQL)


def create_chat_session_record(
    *,
    user_id: str,
    session_id: str | None = None,
    title: str = "New Chat",
    summary: str = "",
    now: float | None = None,
) -> ChatSessionRecord:
    """Build a new canonical chat session row."""

    timestamp = float(now if now is not None else time.time())
    normalized_session_id = str(session_id or "").strip() or str(uuid.uuid4())
    return ChatSessionRecord(
        session_id=normalized_session_id,
        user_id=str(user_id).strip(),
        title=str(title).strip() or "New Chat",
        summary=str(summary),
        created_at=timestamp,
        updated_at=timestamp,
        last_message_at=None,
        last_user_message_at=None,
        last_message_preview="",
        last_user_message_preview="",
        message_count=0,
        archived_at=None,
        deleted_at=None,
    )
