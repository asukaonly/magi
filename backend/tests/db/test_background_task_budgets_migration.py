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


@pytest.mark.asyncio
async def test_v3_preserves_legacy_tasks_and_initializes_usable_budgets(tmp_path: Path) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-v2.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v2")

    spec = BackgroundTaskSpec(
        user_id="user-1",
        session_id="session-1",
        origin_turn_id="turn-1",
        title="Legacy work",
        goal="Resume safely",
    )
    with sqlite3.connect(db_path) as connection:
        for column in _BUDGET_COLUMNS:
            connection.execute(f"ALTER TABLE background_tasks DROP COLUMN {column}")
        connection.execute(
            "INSERT INTO background_tasks(task_id,user_id,session_id,origin_turn_id,title,goal,status,attempt_index,spec_json,created_at,updated_at) VALUES ('legacy-task','user-1','session-1','turn-1','Legacy work','Resume safely','failed',2,?,1,2)",
            (json.dumps(spec.to_dict()),),
        )
        original_columns = [
            row[1] for row in connection.execute("PRAGMA table_info(background_tasks)")
        ]
        original_row = connection.execute(
            "SELECT " + ",".join(original_columns) + " FROM background_tasks"
        ).fetchall()

    command.upgrade(config, "v3")

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(background_tasks)")}
        assert _BUDGET_COLUMNS <= columns
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v3",)

        assert (
            connection.execute(
                "SELECT " + ",".join(original_columns) + " FROM background_tasks"
            ).fetchall()
            == original_row
        )
        assert connection.execute(
            "SELECT task_max_llm_calls,task_llm_calls_used,task_max_worker_launches,task_worker_launches_used FROM background_tasks"
        ).fetchall() == [(None, 0, None, 0)]
    from magi.agent.background.store import BackgroundTaskStore

    store = BackgroundTaskStore(db_path=str(db_path))
    assert await store.ensure_task_execution_budget(
        root_turn_id="legacy-task", max_llm_calls=3, max_worker_launches=2
    ) == (3, 0, 2, 0)
    assert await store.reserve_task_execution_budget(
        root_turn_id="legacy-task",
        resource="llm_calls",
        count=1,
        max_llm_calls=3,
        max_worker_launches=2,
    ) == (True, 3, 1, 2, 0)


@pytest.mark.parametrize("llm_used,worker_used", [(0, 0), (1, 0), (0, 1)])
def test_budget_downgrade_preserves_tasks_and_refuses_used_capacity(
    tmp_path: Path, llm_used: int, worker_used: int
) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-used.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v3")
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
                '{}', 1, 2, 30, ?, 8, ?
            )
            """,
            (json.dumps(spec.to_dict()), llm_used, worker_used),
        )

    with sqlite3.connect(db_path) as connection:
        before = connection.execute("SELECT * FROM background_tasks").fetchall()
    if llm_used or worker_used:
        with pytest.raises(RuntimeError, match="while execution capacity is used"):
            command.downgrade(config, "v2")
        with sqlite3.connect(db_path) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "v3",
            )
            assert connection.execute("SELECT * FROM background_tasks").fetchall() == before
    else:
        command.downgrade(config, "v2")
        with sqlite3.connect(db_path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(background_tasks)")}
            assert _BUDGET_COLUMNS.isdisjoint(columns)
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "v2",
            )
            assert connection.execute(
                "SELECT task_id, status, attempt_index, spec_json FROM background_tasks"
            ).fetchall() == [("task-1", "failed", 1, json.dumps(spec.to_dict()))]
