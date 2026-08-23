from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.agent.background import BackgroundTaskSpec
from magi.db.runner import MIGRATION_TARGETS, _build_config


_BUDGET_COLUMNS = {
    "task_max_llm_calls",
    "task_llm_calls_used",
    "task_max_worker_launches",
    "task_worker_launches_used",
}


def _target():
    return next(target for target in MIGRATION_TARGETS if target.name == "background_tasks")


def test_v3_upgrades_existing_v2_database(tmp_path: Path) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-v2.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v2")

    with sqlite3.connect(db_path) as connection:
        for column in _BUDGET_COLUMNS:
            connection.execute(f"ALTER TABLE background_tasks DROP COLUMN {column}")

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(background_tasks)")}
        assert _BUDGET_COLUMNS <= columns
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v3",)


def test_v3_downgrades_when_budget_is_unused(tmp_path: Path) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-unused.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "head")

    command.downgrade(config, "v2")

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(background_tasks)")}
        assert _BUDGET_COLUMNS.isdisjoint(columns)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v2",)


def test_v3_refuses_downgrade_after_budget_use(tmp_path: Path) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-used.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "head")
    spec = BackgroundTaskSpec(
        user_id="user-1",
        session_id="session-1",
        origin_turn_id="",
        title="Scheduled work",
        goal="run",
    )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO background_tasks (
                task_id, user_id, session_id, origin_turn_id,
                title, goal, status, attempt_index, spec_json,
                result_payload_json, created_at, updated_at,
                task_max_llm_calls, task_llm_calls_used,
                task_max_worker_launches, task_worker_launches_used
            ) VALUES (
                'task-1', 'user-1', 'session-1', '',
                'Scheduled work', 'run', 'failed', 1, ?,
                '{}', 1, 2, 30, 1, 8, 0
            )
            """,
            (json.dumps(spec.to_dict()),),
        )

    with pytest.raises(RuntimeError, match="while execution capacity is used"):
        command.downgrade(config, "v2")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v3",)
