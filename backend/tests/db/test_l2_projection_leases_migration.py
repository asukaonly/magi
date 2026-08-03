"""Schema and upgrade contracts for fenced L2 projection attempts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V38_REVISION = "v38_l2_grounded_claims"
V39_REVISION = "v39_l2_projection_leases"


def _memory_config(db_path: Path):  # type: ignore[no-untyped-def]
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_projection_lease_migration_adds_fencing_and_retry_state(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V38_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO l2_projection_jobs(
                event_id, source, event_type, status, attempt_count,
                created_at, updated_at
            ) VALUES ('event-exhausted', 'chat', 'UserMessage', 'pending', 5, 1.0, 1.0)
            """
        )
        connection.commit()

    command.upgrade(config, V39_REVISION)
    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1]): str(row[2])
            for row in connection.execute("PRAGMA table_info(l2_projection_jobs)")
        }
        assert columns["lease_token"] == "TEXT"
        assert columns["lease_heartbeat_at"] == "REAL"
        assert columns["next_retry_at"] == "REAL"
        assert columns["max_attempts"] == "INTEGER"
        assert columns["terminal_at"] == "REAL"
        status, terminal_at, last_error = connection.execute(
            """
            SELECT status, terminal_at, last_error
            FROM l2_projection_jobs WHERE event_id = 'event-exhausted'
            """
        ).fetchone()
        assert status == "failed"
        assert terminal_at is not None
        assert last_error == "projection_attempt_budget_exhausted_during_upgrade"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE l2_projection_jobs SET max_attempts = 0 WHERE event_id = 'event-exhausted'"
            )


def test_projection_lease_migration_downgrades_without_losing_jobs(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V39_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO l2_projection_jobs(
                event_id, source, event_type, status, attempt_count,
                lease_token, max_attempts, created_at, updated_at
            ) VALUES ('event-retained', 'chat', 'UserMessage', 'queued', 1,
                      'lease-token', 5, 1.0, 1.0)
            """
        )
        connection.commit()

    command.downgrade(config, V38_REVISION)
    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(l2_projection_jobs)")
        }
        assert "lease_token" not in columns
        assert connection.execute(
            "SELECT event_id, status, attempt_count FROM l2_projection_jobs"
        ).fetchall() == [("event-retained", "queued", 1)]
