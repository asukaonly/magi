from __future__ import annotations

import sqlite3

import pytest

from magi.memory.l1.chat_sessions import (
    CHAT_SESSIONS_TABLE,
    create_chat_session_record,
    ensure_chat_sessions_schema_async,
    project_chat_event_to_session,
)


@pytest.mark.asyncio
async def test_chat_sessions_schema_includes_workspace_path(tmp_path) -> None:
    import aiosqlite

    db_path = tmp_path / "chat_sessions.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await ensure_chat_sessions_schema_async(db)
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
        await ensure_chat_sessions_schema_async(db)
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
        workspace_path="/Users/asuka/code/magi",
        now=123.0,
    )

    assert record.workspace_path == "/Users/asuka/code/magi"
