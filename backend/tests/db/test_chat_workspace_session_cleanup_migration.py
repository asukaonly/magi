from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def test_v12_adds_workspace_cleanup_queue_without_changing_chat_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-v11.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v11")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, workspace_path,
                created_at_ms, updated_at_ms
            ) VALUES ('session-a', 'user-a', 'Existing chat', '/workspace/a', 1, 2)
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (CHAT_MIGRATION_HEAD,)
        assert connection.execute(
            """
            SELECT title, workspace_path
            FROM chat_sessions
            WHERE session_id = 'session-a'
            """
        ).fetchone() == ("Existing chat", "/workspace/a")
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(chat_workspace_session_cleanup)"
            ).fetchall()
        }
        assert columns == {"workspace_path", "session_id", "created_at_ms"}
