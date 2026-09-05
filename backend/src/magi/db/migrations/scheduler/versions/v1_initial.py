"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
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
);

CREATE TABLE IF NOT EXISTS target_state (
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    running INTEGER NOT NULL DEFAULT 0,
    last_run_at REAL,
    last_success_at REAL,
    last_error TEXT,
    last_cursor TEXT,
    watermark_ts REAL,
    scheduler_job_id TEXT,
    stats_json TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL,
    PRIMARY KEY (target_type, target_key)
);

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
);

CREATE TABLE IF NOT EXISTS source_sync_jobs (
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
    next_attempt_at REAL NOT NULL DEFAULT 0,
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
);

CREATE INDEX IF NOT EXISTS idx_schedule_executions_schedule_id
    ON schedule_executions(schedule_id);

CREATE INDEX IF NOT EXISTS idx_schedule_executions_target
    ON schedule_executions(target_type, target_key);

CREATE INDEX IF NOT EXISTS idx_schedule_executions_started_at
    ON schedule_executions(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_sync_jobs_status_due_created
    ON source_sync_jobs(status, next_attempt_at ASC, created_at ASC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_sync_jobs_one_outstanding_per_target
    ON source_sync_jobs(target_type, target_key)
    WHERE status IN ('queued', 'running');
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_source_sync_jobs_one_outstanding_per_target;

DROP INDEX IF EXISTS idx_source_sync_jobs_status_due_created;

DROP INDEX IF EXISTS idx_schedule_executions_started_at;

DROP INDEX IF EXISTS idx_schedule_executions_target;

DROP INDEX IF EXISTS idx_schedule_executions_schedule_id;

DROP TABLE IF EXISTS source_sync_jobs;

DROP TABLE IF EXISTS schedule_executions;

DROP TABLE IF EXISTS target_state;

DROP TABLE IF EXISTS schedules;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
