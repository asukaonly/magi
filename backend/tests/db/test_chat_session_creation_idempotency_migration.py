from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def test_v10_adds_session_creation_idempotency_without_changing_chat_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-v9.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v9")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', 'Existing chat', 1, 2)
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            CHAT_MIGRATION_HEAD,
        )
        assert connection.execute(
            "SELECT title FROM chat_sessions WHERE session_id = 'session-1'"
        ).fetchone() == ("Existing chat",)
        connection.execute(
            """
            INSERT INTO chat_session_creation_requests(
                user_id, idempotency_key, session_id, created_at_ms
            ) VALUES ('user-1', 'request-1', 'session-1', 3)
            """
        )
        assert connection.execute(
            """
            SELECT session_id
            FROM chat_session_creation_requests
            WHERE user_id = 'user-1' AND idempotency_key = 'request-1'
            """
        ).fetchone() == ("session-1",)
