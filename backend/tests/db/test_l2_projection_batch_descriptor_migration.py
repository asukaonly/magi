"""Schema contracts for queue-issued L2 projection batch descriptors."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V41_REVISION = "v41_l2_claim_subject_revisions"
V42_REVISION = "v42_l2_projection_batch_descriptors"


def _memory_config(db_path: Path):  # type: ignore[no-untyped-def]
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_batch_descriptor_migration_recovers_unbound_in_flight_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V41_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO l2_projection_jobs(
                event_id, source, event_type, status, attempt_count,
                lease_token, claimed_by, claimed_at, started_at,
                max_attempts, replay_requested, created_at, updated_at
            ) VALUES
                ('event-queued', 'chat', 'UserMessage', 'queued', 1,
                 'lease-queued', 'old-worker', 2.0, NULL, 5, 0, 1.0, 2.0),
                ('event-running', 'chat', 'UserMessage', 'running', 5,
                 'lease-running', 'old-worker', 2.0, 3.0, 5, 0, 1.0, 3.0),
                ('event-z-replay', 'chat', 'UserMessage', 'running', 5,
                 'lease-replay', 'old-worker', 2.0, 3.0, 5, 1, 1.0, 3.0)
            """
        )
        connection.commit()

    command.upgrade(config, V42_REVISION)
    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1]): str(row[2])
            for row in connection.execute("PRAGMA table_info(l2_projection_jobs)")
        }
        assert columns["batch_attempt_key"] == "TEXT"
        assert columns["batch_descriptor_json"] == "TEXT"
        assert columns["batch_bound_at"] == "REAL"
        rows = connection.execute(
            """
            SELECT event_id, status, lease_token, claimed_by, started_at,
                   next_retry_at, terminal_at, last_error,
                   batch_attempt_key, batch_descriptor_json, batch_bound_at
            FROM l2_projection_jobs
            ORDER BY event_id
            """
        ).fetchall()
        assert rows[0][:5] == ("event-queued", "pending", None, None, None)
        assert rows[0][5] is not None
        assert rows[0][6] is None
        assert rows[0][7] == "projection_attempt_recovered_during_batch_descriptor_upgrade"
        assert rows[0][8:] == (None, None, None)
        assert rows[1][:5] == ("event-running", "failed", None, None, None)
        assert rows[1][5] is None
        assert rows[1][6] is not None
        assert (
            rows[1][7]
            == "projection_attempt_budget_exhausted_during_batch_descriptor_upgrade"
        )
        assert rows[1][8:] == (None, None, None)
        assert rows[2][:5] == ("event-z-replay", "pending", None, None, None)
        assert rows[2][5] is None
        assert rows[2][6] is None
        assert rows[2][7] is None
        assert rows[2][8:] == (None, None, None)
        assert connection.execute(
            """
            SELECT attempt_count, replay_requested
            FROM l2_projection_jobs
            WHERE event_id = 'event-z-replay'
            """
        ).fetchone() == (0, 0)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE l2_projection_jobs
                SET batch_descriptor_json = 'not-json'
                WHERE event_id = 'event-queued'
                """
            )


def test_batch_descriptor_migration_downgrades_without_losing_jobs(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V42_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO l2_projection_jobs(
                event_id, source, event_type, status, attempt_count,
                created_at, updated_at
            ) VALUES ('event-retained', 'chat', 'UserMessage', 'pending', 0, 1.0, 1.0)
            """
        )
        connection.commit()

    command.downgrade(config, V41_REVISION)
    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(l2_projection_jobs)")
        }
        assert "batch_attempt_key" not in columns
        assert "batch_descriptor_json" not in columns
        assert "batch_bound_at" not in columns
        assert connection.execute(
            "SELECT event_id, status FROM l2_projection_jobs"
        ).fetchall() == [("event-retained", "pending")]
