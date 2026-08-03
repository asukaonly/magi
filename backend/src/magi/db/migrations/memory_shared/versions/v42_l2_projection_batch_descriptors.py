"""Bind each queued L2 projection attempt to its exact batch members."""

from __future__ import annotations

from alembic import op

revision = "v42_l2_projection_batch_descriptors"
down_revision = "v41_l2_claim_subject_revisions"
branch_labels = None
depends_on = None


ALTER_STATEMENTS = (
    """
ALTER TABLE l2_projection_jobs
    ADD COLUMN batch_attempt_key TEXT
        CHECK (batch_attempt_key IS NULL OR batch_attempt_key LIKE 'l2pa_%')
""",
    """
ALTER TABLE l2_projection_jobs
    ADD COLUMN batch_descriptor_json TEXT
        CHECK (batch_descriptor_json IS NULL OR json_valid(batch_descriptor_json))
""",
    "ALTER TABLE l2_projection_jobs ADD COLUMN batch_bound_at REAL",
    """
UPDATE l2_projection_jobs
SET status = CASE
        WHEN replay_requested = 0 AND attempt_count >= max_attempts THEN 'failed'
        ELSE 'pending'
    END,
    attempt_count = CASE
        WHEN replay_requested = 1 THEN 0
        ELSE attempt_count
    END,
    lease_token = NULL,
    lease_heartbeat_at = NULL,
    next_retry_at = CASE
        WHEN replay_requested = 1 THEN NULL
        WHEN attempt_count >= max_attempts THEN NULL
        ELSE CAST(strftime('%s', 'now') AS REAL)
    END,
    terminal_at = CASE
        WHEN replay_requested = 0 AND attempt_count >= max_attempts
            THEN CAST(strftime('%s', 'now') AS REAL)
        ELSE NULL
    END,
    replay_requested = 0,
    claimed_by = NULL,
    claimed_at = NULL,
    started_at = NULL,
    completed_at = NULL,
    last_error = CASE
        WHEN replay_requested = 1 THEN NULL
        WHEN attempt_count >= max_attempts
            THEN 'projection_attempt_budget_exhausted_during_batch_descriptor_upgrade'
        ELSE 'projection_attempt_recovered_during_batch_descriptor_upgrade'
    END,
    updated_at = CAST(strftime('%s', 'now') AS REAL)
WHERE status IN ('queued', 'running')
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_batch_attempt
    ON l2_projection_jobs(batch_attempt_key, status, event_id)
""",
)
SCHEMA_SQL = ";\n".join(statement.strip() for statement in ALTER_STATEMENTS) + ";"


def upgrade() -> None:
    for statement in ALTER_STATEMENTS:
        op.execute(statement.strip())


def schema_sql_for_fresh_database() -> str:
    """Return the release schema addition for a fresh shared-memory database."""

    return SCHEMA_SQL


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_l2_projection_jobs_batch_attempt")
    op.execute("ALTER TABLE l2_projection_jobs DROP COLUMN batch_bound_at")
    op.execute("ALTER TABLE l2_projection_jobs DROP COLUMN batch_descriptor_json")
    op.execute("ALTER TABLE l2_projection_jobs DROP COLUMN batch_attempt_key")


__all__ = [
    "ALTER_STATEMENTS",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
