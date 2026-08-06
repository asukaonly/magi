"""Add durable one-shot history import jobs and normalized records."""

from __future__ import annotations

from alembic import op

revision = "v36_history_imports"
down_revision = "v35_l0_attention_state"
branch_labels = None
depends_on = None


CREATE_STATEMENTS = (
    """
CREATE TABLE IF NOT EXISTS history_import_jobs (
    job_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    source_files_json TEXT NOT NULL DEFAULT '[]',
    detected_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    total_records INTEGER NOT NULL DEFAULT 0,
    meaningful_records INTEGER NOT NULL DEFAULT 0,
    quick_target_records INTEGER NOT NULL DEFAULT 200,
    quick_max_records INTEGER NOT NULL DEFAULT 500,
    quick_imported_count INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    projected_count INTEGER NOT NULL DEFAULT 0,
    self_participants_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    quick_ready INTEGER NOT NULL DEFAULT 0,
    error_text TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    deleted_at REAL
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_history_import_jobs_fingerprint
    ON history_import_jobs(source_fingerprint, deleted_at, created_at DESC)
""",
    """
CREATE INDEX IF NOT EXISTS idx_history_import_jobs_status
    ON history_import_jobs(status, updated_at)
""",
    """
CREATE TABLE IF NOT EXISTS history_import_source_records (
    source_record_key TEXT PRIMARY KEY,
    file_fingerprint TEXT NOT NULL,
    source_name TEXT NOT NULL,
    parsed_session_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    session_seq INTEGER NOT NULL,
    speaker_name TEXT NOT NULL,
    speaker_role TEXT NOT NULL DEFAULT 'unknown',
    content TEXT NOT NULL,
    event_at REAL NOT NULL,
    timestamp_confidence TEXT NOT NULL,
    meaningful INTEGER NOT NULL DEFAULT 0,
    event_id TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_history_import_source_file_order
    ON history_import_source_records(file_fingerprint, session_id, session_seq)
""",
    """
CREATE TABLE IF NOT EXISTS history_import_job_records (
    job_record_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    raw_state TEXT NOT NULL DEFAULT 'pending',
    projection_state TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(job_id) REFERENCES history_import_jobs(job_id),
    FOREIGN KEY(source_record_key) REFERENCES history_import_source_records(source_record_key),
    UNIQUE(job_id, source_record_key)
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_history_import_job_records_source
    ON history_import_job_records(source_record_key, job_id)
""",
    """
CREATE INDEX IF NOT EXISTS idx_history_import_job_records_job
    ON history_import_job_records(job_id, source_record_key)
""",
    """
CREATE INDEX IF NOT EXISTS idx_history_import_job_records_work
    ON history_import_job_records(job_id, raw_state, projection_state)
""",
)
CREATE_SQL = ";\n".join(
    statement.strip() for statement in CREATE_STATEMENTS
) + ";"

DROP_STATEMENTS = (
    "DROP INDEX IF EXISTS idx_history_import_job_records_work",
    "DROP INDEX IF EXISTS idx_history_import_job_records_job",
    "DROP INDEX IF EXISTS idx_history_import_job_records_source",
    "DROP TABLE IF EXISTS history_import_job_records",
    "DROP INDEX IF EXISTS idx_history_import_source_file_order",
    "DROP TABLE IF EXISTS history_import_source_records",
    "DROP INDEX IF EXISTS idx_history_import_jobs_status",
    "DROP INDEX IF EXISTS idx_history_import_jobs_fingerprint",
    "DROP TABLE IF EXISTS history_import_jobs",
)


def upgrade() -> None:
    for statement in CREATE_STATEMENTS:
        op.execute(statement.strip())


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a fresh shared-memory database."""

    return CREATE_SQL


def downgrade() -> None:
    for statement in DROP_STATEMENTS:
        op.execute(statement)


__all__ = [
    "CREATE_SQL",
    "CREATE_STATEMENTS",
    "DROP_STATEMENTS",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
