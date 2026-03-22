from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _list_tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {str(row[0]) for row in cur.fetchall()}
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_database_initializer_creates_chat_db_with_chat_tables(tmp_path: Path) -> None:
    from magi.core.database_initializer import DatabaseInitializer

    data_dir = tmp_path / "runtime-data"
    initializer = DatabaseInitializer(data_dir)

    await initializer.initialize_all()

    chat_db_path = data_dir / "chat.db"
    assert chat_db_path.exists()
    tables = _list_tables(chat_db_path)
    assert "chat_sessions" in tables
    assert "chat_turns" in tables
    assert "chat_messages" in tables


@pytest.mark.asyncio
async def test_backfill_chat_store_from_legacy_l1_is_idempotent(tmp_path: Path) -> None:
    from magi.chat import ChatStore
    from magi.chat.migration import backfill_chat_store_from_legacy

    l1_db_path = tmp_path / "l1_events.db"
    chat_db_path = tmp_path / "chat.db"

    conn = sqlite3.connect(str(l1_db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE chat_sessions (
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
                archived_at REAL,
                deleted_at REAL
            );

            CREATE TABLE fact_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                session_id TEXT,
                turn_id TEXT,
                user_id TEXT,
                content TEXT,
                timestamp REAL NOT NULL,
                deleted_at REAL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO chat_sessions (
                session_id, user_id, title, title_overridden, summary, created_at, updated_at,
                last_message_at, last_user_message_at, last_message_preview,
                last_user_message_preview, message_count, archived_at, deleted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "session-1",
                "user-1",
                "Legacy Chat",
                1,
                "",
                1.0,
                2.0,
                2.0,
                1.0,
                "Legacy answer",
                "Legacy question",
                2,
                None,
                None,
            ),
        )
        conn.executemany(
            """
            INSERT INTO fact_events (
                event_id, event_type, session_id, turn_id, user_id, content, timestamp, deleted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("evt-1", "UserMessage", "session-1", "turn-1", "user-1", "Legacy question", 1.0, None),
                ("evt-2", "AIResponse", "session-1", "turn-1", "user-1", "Legacy answer", 2.0, None),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    store = ChatStore(db_path=str(chat_db_path))
    await store.initialize()

    try:
        await backfill_chat_store_from_legacy(chat_store=store, legacy_l1_db_path=l1_db_path)
        await backfill_chat_store_from_legacy(chat_store=store, legacy_l1_db_path=l1_db_path)
    finally:
        await store.shutdown()

    conn = sqlite3.connect(str(chat_db_path))
    try:
        migrated_session = conn.execute(
            "SELECT title, message_count FROM chat_sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()
        migrated_turns = conn.execute(
            "SELECT turn_id, status, response_mode FROM chat_turns ORDER BY turn_id",
        ).fetchall()
        migrated_messages = conn.execute(
            "SELECT message_id, message_kind, content_text FROM chat_messages ORDER BY sequence_no",
        ).fetchall()
    finally:
        conn.close()

    assert migrated_session == ("Legacy Chat", 2)
    assert migrated_turns == [("turn-1", "completed", "final_only")]
    assert migrated_messages == [
        ("evt-1", "user_text", "Legacy question"),
        ("evt-2", "assistant_final", "Legacy answer"),
    ]
