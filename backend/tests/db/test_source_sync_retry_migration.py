from __future__ import annotations

import sqlite3

import pytest

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


@pytest.mark.asyncio
async def test_scheduler_v1_upgrades_source_sync_jobs_for_durable_retries(tmp_path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "scheduler")
    db_path = tmp_path / "scheduler-v1.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v1")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX idx_source_sync_jobs_status_due_created")
        connection.execute("ALTER TABLE source_sync_jobs DROP COLUMN next_attempt_at")
        connection.execute("""
            CREATE INDEX idx_source_sync_jobs_status_created
            ON source_sync_jobs(status, created_at ASC)
            """)

    with sqlite3.connect(db_path) as connection:
        for identity, status in [("queued-job", "queued"), ("running-job", "running")]:
            connection.execute(
                "INSERT INTO source_sync_jobs(job_id,schedule_id,execution_id,target_type,target_key,plugin_id,source_type,status,payload_json,created_at,attempt_count) VALUES (?, 'schedule', 'execution', 'source_sync', ?, 'calendar', 'calendar', ?, ?,1,2)",
                (identity, identity, status, '{"cursor":"keep"}'),
            )
            connection.execute(
                "INSERT INTO target_state(target_type,target_key,running,updated_at) VALUES ('source_sync',?,?,1)",
                (identity, int(status == "running")),
            )
        columns_before = [
            row[1] for row in connection.execute("PRAGMA table_info(source_sync_jobs)")
        ]
        before = connection.execute(
            "SELECT " + ",".join(columns_before) + " FROM source_sync_jobs ORDER BY job_id"
        ).fetchall()
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(source_sync_jobs)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(source_sync_jobs)")}
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()

    assert "next_attempt_at" in columns
    assert "idx_source_sync_jobs_status_due_created" in indexes
    assert "idx_source_sync_jobs_status_created" not in indexes
    assert revision == ("v3",)

    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT " + ",".join(columns_before) + " FROM source_sync_jobs ORDER BY job_id"
            ).fetchall()
            == before
        )
        assert connection.execute(
            "SELECT job_id,next_attempt_at FROM source_sync_jobs ORDER BY job_id"
        ).fetchall() == [("queued-job", 0.0), ("running-job", 0.0)]
    from magi.scheduler.repository import ScheduleRepository

    repository = ScheduleRepository(db_path)
    queued = await repository.claim_next_source_sync_job(claimed_by="worker-one")
    assert (queued["job_id"], queued["status"], queued["attempt_count"], queued["payload"]) == (
        "queued-job",
        "running",
        3,
        {"cursor": "keep"},
    )
    assert await repository.claim_next_source_sync_job(claimed_by="worker-two") is None
    assert await repository.recover_running_source_sync_jobs() == 2
    reclaimed = await repository.claim_next_source_sync_job(claimed_by="worker-two")
    assert reclaimed["payload"] == {"cursor": "keep"}
    assert reclaimed["status"] == "running"
