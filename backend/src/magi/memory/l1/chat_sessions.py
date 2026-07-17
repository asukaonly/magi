"""Canonical chat session storage helpers."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import aiosqlite

from ...events.events import EventTypes

CHAT_SESSIONS_TABLE = "chat_sessions"


@dataclass(slots=True)
class _ChatSessionProjection:
    user_id: str
    session_id: str
    preview: str
    timestamp: float


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


_INSERT_CHAT_SESSION_SQL = f"""
INSERT INTO {CHAT_SESSIONS_TABLE} (
    session_id, user_id, title, title_overridden, summary, created_at, updated_at,
    last_message_at, last_user_message_at, last_message_preview,
    last_user_message_preview, message_count, workspace_path, archived_at, deleted_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(session_id) DO NOTHING
"""

_UPDATE_USER_MESSAGE_SQL = f"""
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
"""

_UPDATE_AI_RESPONSE_SQL = f"""
UPDATE {CHAT_SESSIONS_TABLE}
SET
    updated_at = ?,
    last_message_at = ?,
    last_message_preview = ?,
    message_count = message_count + 1
WHERE session_id = ?
  AND user_id = ?
  AND deleted_at IS NULL
"""


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

    projection = _chat_session_projection(
        user_id=user_id,
        session_id=session_id,
        content=content,
        timestamp=timestamp,
    )
    if projection is None:
        return

    await _ensure_projected_chat_session_row(db, projection)
    if event_type == EventTypes.USER_MESSAGE:
        await _project_user_message_to_session(db, projection)
        return

    if event_type == EventTypes.AI_RESPONSE:
        await _project_ai_response_to_session(db, projection)


async def rebuild_chat_session_projection(
    db: aiosqlite.Connection,
    *,
    session_id: str,
) -> None:
    """Rebuild one L1 chat preview from its remaining active source rows."""

    latest_cursor = await db.execute(
        """
        SELECT content, timestamp
        FROM fact_events
        WHERE session_id = ? AND deleted_at IS NULL
          AND event_type IN (?, ?)
        ORDER BY timestamp DESC, created_at DESC, event_id DESC
        LIMIT 1
        """,
        (session_id, EventTypes.USER_MESSAGE, EventTypes.AI_RESPONSE),
    )
    latest = await latest_cursor.fetchone()
    latest_user_cursor = await db.execute(
        """
        SELECT content, timestamp
        FROM fact_events
        WHERE session_id = ? AND deleted_at IS NULL
          AND event_type = ?
        ORDER BY timestamp DESC, created_at DESC, event_id DESC
        LIMIT 1
        """,
        (session_id, EventTypes.USER_MESSAGE),
    )
    latest_user = await latest_user_cursor.fetchone()
    count_cursor = await db.execute(
        """
        SELECT COUNT(*)
        FROM fact_events
        WHERE session_id = ? AND deleted_at IS NULL
          AND event_type IN (?, ?)
        """,
        (session_id, EventTypes.USER_MESSAGE, EventTypes.AI_RESPONSE),
    )
    count_row = await count_cursor.fetchone()
    latest_preview = str(latest[0] or "").strip()[:120] if latest is not None else ""
    latest_timestamp = float(latest[1]) if latest is not None else None
    user_preview = str(latest_user[0] or "").strip()[:120] if latest_user is not None else ""
    user_timestamp = float(latest_user[1]) if latest_user is not None else None
    await db.execute(
        f"""
        UPDATE {CHAT_SESSIONS_TABLE}
        SET updated_at = ?,
            last_message_at = ?,
            last_user_message_at = ?,
            last_message_preview = ?,
            last_user_message_preview = ?,
            message_count = ?
        WHERE session_id = ? AND deleted_at IS NULL
        """,
        (
            latest_timestamp or user_timestamp or time.time(),
            latest_timestamp,
            user_timestamp,
            latest_preview,
            user_preview,
            int(count_row[0] or 0) if count_row is not None else 0,
            session_id,
        ),
    )


async def retire_chat_session_projection(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    deleted_at: float,
) -> None:
    """Scrub and retire one L1 session projection after explicit deletion."""

    await db.execute(
        f"""
        UPDATE {CHAT_SESSIONS_TABLE}
        SET title = '',
            summary = '',
            updated_at = ?,
            last_message_at = NULL,
            last_user_message_at = NULL,
            last_message_preview = '',
            last_user_message_preview = '',
            message_count = 0,
            workspace_path = NULL,
            archived_at = NULL,
            deleted_at = ?
        WHERE session_id = ?
        """,
        (deleted_at, deleted_at, session_id),
    )


def _chat_session_projection(
    *,
    user_id: str | None,
    session_id: str | None,
    content: str | None,
    timestamp: float,
) -> _ChatSessionProjection | None:
    normalized_user_id = str(user_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_content = str(content or "").strip()
    if not normalized_user_id or not normalized_session_id or not normalized_content:
        return None
    return _ChatSessionProjection(
        user_id=normalized_user_id,
        session_id=normalized_session_id,
        preview=normalized_content[:120],
        timestamp=float(timestamp),
    )


async def _ensure_projected_chat_session_row(
    db: aiosqlite.Connection,
    projection: _ChatSessionProjection,
) -> None:
    await db.execute(
        _INSERT_CHAT_SESSION_SQL,
        (
            projection.session_id,
            projection.user_id,
            "",
            0,
            "",
            projection.timestamp,
            projection.timestamp,
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


async def _project_user_message_to_session(
    db: aiosqlite.Connection,
    projection: _ChatSessionProjection,
) -> None:
    await db.execute(
        _UPDATE_USER_MESSAGE_SQL,
        (
            projection.timestamp,
            projection.timestamp,
            projection.timestamp,
            projection.preview,
            projection.preview,
            projection.session_id,
            projection.user_id,
        ),
    )


async def _project_ai_response_to_session(
    db: aiosqlite.Connection,
    projection: _ChatSessionProjection,
) -> None:
    await db.execute(
        _UPDATE_AI_RESPONSE_SQL,
        (
            projection.timestamp,
            projection.timestamp,
            projection.preview,
            projection.session_id,
            projection.user_id,
        ),
    )
