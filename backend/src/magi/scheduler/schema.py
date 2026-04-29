"""SQLite schema management for scheduler persistence."""

from __future__ import annotations

import aiosqlite


async def ensure_scheduler_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS schedules (
            schedule_id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_key TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_config TEXT NOT NULL,
            target_payload TEXT NOT NULL,
            metadata TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            job_id TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS target_state (
            target_type TEXT NOT NULL,
            target_key TEXT NOT NULL,
            running INTEGER NOT NULL DEFAULT 0,
            last_run_at REAL,
            last_success_at REAL,
            last_error TEXT,
            last_cursor TEXT,
            watermark_ts REAL,
            next_run_at REAL,
            scheduler_job_id TEXT,
            stats_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL,
            PRIMARY KEY (target_type, target_key)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_executions (
            execution_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_key TEXT NOT NULL,
            manual INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            started_at REAL NOT NULL,
            finished_at REAL,
            duration_ms REAL,
            result_message TEXT,
            error TEXT,
            stats_json TEXT NOT NULL DEFAULT '{}',
            next_cursor TEXT,
            watermark_ts REAL,
            scheduler_job_id TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_sync_jobs (
            job_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_key TEXT NOT NULL,
            plugin_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            manual INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            claimed_at REAL,
            started_at REAL,
            finished_at REAL,
            claimed_by TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            result_message TEXT,
            stats_json TEXT NOT NULL DEFAULT '{}',
            next_cursor TEXT,
            watermark_ts REAL
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_executions_schedule_id ON schedule_executions(schedule_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_executions_target ON schedule_executions(target_type, target_key)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_executions_started_at ON schedule_executions(started_at DESC)"
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sensor_sync_jobs_status_created
        ON sensor_sync_jobs(status, created_at ASC)
        """
    )
    await db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sensor_sync_jobs_one_outstanding_per_target
        ON sensor_sync_jobs(target_type, target_key)
        WHERE status IN ('queued', 'running')
        """
    )


__all__ = ["ensure_scheduler_schema"]