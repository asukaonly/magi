from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def test_v13_adds_root_turn_execution_budgets_without_changing_chat_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-v12.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v12")
    with sqlite3.connect(db_path) as connection:
        # The current v1 baseline includes the table for fresh installs. Remove
        # it to reproduce a genuine pre-v13 database before testing the delta.
        connection.execute("DROP TABLE chat_task_execution_budgets")
        assert (
            connection.execute(
                """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'chat_task_execution_budgets'
            """
            ).fetchone()
            is None
        )
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-a', 'user-a', 'Existing chat', 1, 2)
            """
        )
        connection.execute(
            """
            INSERT INTO chat_turns(
                turn_id, session_id, user_id, status, response_mode,
                created_at_ms, updated_at_ms
            ) VALUES (
                'turn-a', 'session-a', 'user-a', 'running', 'final_only', 1, 2
            )
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            CHAT_MIGRATION_HEAD,
        )
        assert connection.execute(
            "SELECT title FROM chat_sessions WHERE session_id = 'session-a'"
        ).fetchone() == ("Existing chat",)
        table_info = connection.execute("PRAGMA table_info(chat_task_execution_budgets)").fetchall()
        columns = {row[1] for row in table_info}
        assert columns == {
            "root_turn_id",
            "max_llm_calls",
            "llm_calls_used",
            "max_worker_launches",
            "worker_launches_used",
            "created_at_ms",
        }
        root_column = next(row for row in table_info if row[1] == "root_turn_id")
        assert root_column[3] == 1
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(chat_task_execution_budgets)"
        ).fetchall()
        assert any(
            row[2] == "chat_turns"
            and row[3] == "root_turn_id"
            and row[4] == "turn_id"
            and row[6].upper() == "CASCADE"
            for row in foreign_keys
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO chat_task_execution_budgets(
                    root_turn_id, max_llm_calls, llm_calls_used,
                    max_worker_launches, worker_launches_used, created_at_ms
                ) VALUES (NULL, 30, 0, 8, 0, 3)
                """
            )
