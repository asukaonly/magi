from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.agent.background import BackgroundTaskSpec
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _target():
    return next(target for target in MIGRATION_TARGETS if target.name == "background_tasks")


def _create_legacy_terminal_row(connection: sqlite3.Connection) -> None:
    spec = BackgroundTaskSpec(
        user_id="user-1",
        session_id="session-1",
        origin_turn_id="turn-1",
        title="Already finished",
        goal="legacy work",
    )
    connection.execute(
        """
        INSERT INTO background_tasks (
            task_id, user_id, session_id, origin_turn_id,
            title, goal, status, attempt_index, spec_json,
            orchestration_id, user_task_id, summary, result_payload_json,
            error, cancel_reason, created_at, started_at, finished_at,
            updated_at
        ) VALUES (
            'legacy-task', 'user-1', 'session-1', 'turn-1',
            'Already finished', 'legacy work', 'succeeded', 0, ?,
            NULL, NULL, 'done before upgrade', '{}',
            NULL, NULL, 1, 2, 3, 3
        )
        """,
        (json.dumps(spec.to_dict()),),
    )


def test_v2_upgrades_legacy_database_without_replaying_old_completions(
    tmp_path: Path,
) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-v1.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v1")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX idx_bg_completion_intents_state_created")
        connection.execute("DROP TABLE background_task_completion_intents")
        _create_legacy_terminal_row(connection)

    command.upgrade(config, "v2")

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(background_task_completion_intents)")
        }
        assert {
            "intent_json",
            "composed_body",
            "claim_token",
            "claimed_at",
            "state",
            "handled_at",
        } <= columns
        assert connection.execute(
            "SELECT COUNT(*) FROM background_task_completion_intents"
        ).fetchone() == (0,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v2",)


def test_v2_downgrades_when_no_completion_is_pending(tmp_path: Path) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-empty.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v2")

    command.downgrade(config, "v1")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'background_task_completion_intents'
            """
        ).fetchone() == (0,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v1",)


def test_v2_refuses_downgrade_while_completion_is_pending(
    tmp_path: Path,
) -> None:
    target = _target()
    db_path = tmp_path / "background-tasks-pending.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v2")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO background_task_completion_intents (
                task_id, attempt_index, task_json, intent_json,
                composed_body, claim_token, claimed_at,
                state, created_at, handled_at
            ) VALUES (
                'task-1', 0, '{}', NULL, NULL, NULL, NULL,
                'pending', 1, NULL
            )
            """
        )

    with pytest.raises(
        RuntimeError,
        match="while delivery is pending",
    ):
        command.downgrade(config, "v1")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v2",)
        assert connection.execute(
            "SELECT COUNT(*) FROM background_task_completion_intents"
        ).fetchone() == (1,)
