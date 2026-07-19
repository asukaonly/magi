"""Migration coverage for durable chat clear barriers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def _barrier_contract(connection: sqlite3.Connection) -> tuple[object, ...]:
    columns = tuple(
        connection.execute(
            "PRAGMA table_info(chat_cleared_session_scopes)"
        ).fetchall()
    )
    triggers = tuple(
        connection.execute(
            """
            SELECT name, sql
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name LIKE '%reject_%session'
            ORDER BY name
            """
        ).fetchall()
    )
    return columns, triggers


def test_v7_adds_durable_clear_barriers_without_changing_chat_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-v6.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v6")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', 'Existing chat', 1, 2)
            """
        )
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms,
                deleted_at_ms
            ) VALUES ('session-deleted', 'user-1', '', 1, 3, 3)
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (CHAT_MIGRATION_HEAD,)
        assert connection.execute(
            "SELECT title FROM chat_sessions WHERE session_id = 'session-1'"
        ).fetchone() == ("Existing chat",)
        assert connection.execute(
            """
            SELECT cleared_at_ms
            FROM chat_cleared_session_scopes
            WHERE session_id = 'session-deleted'
            """
        ).fetchone() == (3,)
        with pytest.raises(sqlite3.IntegrityError, match="session was cleared"):
            connection.execute(
                """
                INSERT INTO chat_sessions(
                    session_id, user_id, title, created_at_ms, updated_at_ms
                ) VALUES ('SESSION-DELETED', 'user-1', 'Late chat', 3, 3)
                ON CONFLICT(session_id) DO UPDATE SET
                    deleted_at_ms = NULL,
                    title = excluded.title
                """
            )
        connection.execute(
            """
            INSERT INTO chat_cleared_session_scopes(session_id, cleared_at_ms)
            VALUES ('session-cleared', 123)
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="session was cleared"):
            connection.execute(
                """
                INSERT INTO chat_sessions(
                    session_id, user_id, title, created_at_ms, updated_at_ms
                ) VALUES ('session-cleared', 'user-1', 'Late chat', 3, 3)
                """
            )
        connection.execute(
            """
            INSERT INTO chat_global_clear_intent(
                intent_key, requested_at_ms, session_count
            ) VALUES ('global', 124, 1)
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="session was cleared"):
            connection.execute(
                """
                INSERT INTO chat_sessions(
                    session_id, user_id, title, created_at_ms, updated_at_ms
                ) VALUES ('session-during-clear', 'user-1', 'Racing chat', 4, 4)
                """
            )
        with pytest.raises(sqlite3.IntegrityError, match="session is unavailable"):
            connection.execute(
                """
                INSERT INTO chat_messages(
                    message_id, session_id, user_id, role, message_kind,
                    created_at_ms, sequence_no
                ) VALUES (
                    'message-during-clear', 'session-1', 'user-1', 'assistant',
                    'assistant_final', 4, 1
                )
                """
            )


def test_v7_clear_barriers_match_fresh_baseline(tmp_path: Path) -> None:
    upgraded_path = tmp_path / "upgraded.db"
    upgraded_config = _chat_config(upgraded_path)
    command.upgrade(upgraded_config, "v6")
    command.upgrade(upgraded_config, "head")

    baseline_path = tmp_path / "baseline.db"
    command.upgrade(_chat_config(baseline_path), "v1")

    with sqlite3.connect(upgraded_path) as upgraded, sqlite3.connect(
        baseline_path
    ) as baseline:
        assert _barrier_contract(upgraded) == _barrier_contract(baseline)
