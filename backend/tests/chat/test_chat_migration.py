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
