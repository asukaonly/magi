from __future__ import annotations

import sqlite3

import pytest

from magi.memory.l1.chat_sessions import (
    CHAT_SESSIONS_TABLE,
    create_chat_session_record,
    project_chat_event_to_session,
)

# Schema ownership moved to Alembic (commit bb7eb92d); the per-connection
# ``ensure_chat_sessions_schema_async`` helper was removed. The canonical
# ``chat_sessions`` projection DDL now lives in the L1 migration
# (src/magi/db/migrations/l1/versions/0001_initial.py). Mirror it here so these
# unit tests can exercise the projection helpers against the canonical shape.
_CHAT_SESSIONS_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {CHAT_SESSIONS_TABLE} (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    title_overridden INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_message_at REAL,
    last_user_message_at REAL,
    last_message_preview TEXT NOT NULL DEFAULT '',
    last_user_message_preview TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    workspace_path TEXT,
    archived_at REAL,
    deleted_at REAL
);
"""


async def _ensure_chat_sessions_schema(db) -> None:
    await db.executescript(_CHAT_SESSIONS_SCHEMA_SQL)


@pytest.mark.asyncio
async def test_chat_sessions_schema_includes_workspace_path(tmp_path) -> None:
    import aiosqlite

    db_path = tmp_path / "chat_sessions.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await _ensure_chat_sessions_schema(db)
        await db.commit()

    conn = sqlite3.connect(str(db_path))
    try:
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({CHAT_SESSIONS_TABLE})").fetchall()
        }
    finally:
        conn.close()

    assert "workspace_path" in columns


@pytest.mark.asyncio
async def test_project_chat_event_to_session_preserves_workspace_path_column_shape(tmp_path) -> None:
    import aiosqlite

    db_path = tmp_path / "chat_sessions.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await _ensure_chat_sessions_schema(db)
        await project_chat_event_to_session(
            db,
            user_id="user-1",
            session_id="session-1",
            event_type="UserMessage",
            content="hello",
            timestamp=123.0,
        )
        await db.commit()

    conn = sqlite3.connect(str(db_path))
    try:
        workspace_path = conn.execute(
            f"SELECT workspace_path FROM {CHAT_SESSIONS_TABLE} WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
    finally:
        conn.close()

    assert workspace_path is not None
    assert workspace_path[0] is None


def test_create_chat_session_record_keeps_workspace_path() -> None:
    record = create_chat_session_record(
        user_id="user-1",
        session_id="session-1",
        workspace_path="/tmp/magi",
        now=123.0,
    )

    assert record.workspace_path == "/tmp/magi"
