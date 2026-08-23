from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config


def _target():
    return next(target for target in MIGRATION_TARGETS if target.name == "background_tasks")


def test_v4_upgrades_existing_v3_database(tmp_path: Path) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-v3.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v3")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX idx_tool_effect_attempts_scope")
        connection.execute("DROP INDEX idx_tool_effect_attempts_semantic_state")
        connection.execute("DROP TABLE tool_effect_attempts")

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v4",)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(tool_effect_attempts)")}
        assert {
            "attempt_id",
            "semantic_key",
            "scope_id",
            "tool_name",
            "replay_policy",
            "arguments_digest",
            "state",
        } <= columns


def test_v4_refuses_downgrade_with_uncertain_effect(tmp_path: Path) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-uncertain.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO tool_effect_attempts (
                attempt_id, semantic_key, scope_id, tool_name, replay_policy,
                arguments_digest, state, started_at, updated_at
            ) VALUES (
                'effect-1', 'semantic-1', 'turn:turn-1', 'file_write',
                'reconcilable', 'digest', 'uncertain', 1, 2
            )
            """
        )

    with pytest.raises(RuntimeError, match="while outcomes are unresolved"):
        command.downgrade(config, "v3")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v4",)


def test_v4_downgrades_after_terminal_effect(tmp_path: Path) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-terminal.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO tool_effect_attempts (
                attempt_id, semantic_key, scope_id, tool_name, replay_policy,
                arguments_digest, state, started_at, finished_at, updated_at
            ) VALUES (
                'effect-1', 'semantic-1', 'turn:turn-1', 'file_write',
                'reconcilable', 'digest', 'succeeded', 1, 2, 2
            )
            """
        )

    command.downgrade(config, "v3")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v3",)
        assert connection.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'table' AND name = 'tool_effect_attempts'
            """
        ).fetchone() == (0,)
