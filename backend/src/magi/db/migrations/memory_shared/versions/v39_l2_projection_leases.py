"""Fence durable L2 projection attempts with per-claim lease tokens."""

from __future__ import annotations

from alembic import op

revision = "v39_l2_projection_leases"
down_revision = "v38_l2_grounded_claims"
branch_labels = None
depends_on = None

ALTER_STATEMENTS = (
    "ALTER TABLE l2_projection_jobs ADD COLUMN lease_token TEXT",
    "ALTER TABLE l2_projection_jobs ADD COLUMN lease_heartbeat_at REAL",
    "ALTER TABLE l2_projection_jobs ADD COLUMN next_retry_at REAL",
    """
ALTER TABLE l2_projection_jobs
    ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0)
""",
    "ALTER TABLE l2_projection_jobs ADD COLUMN terminal_at REAL",
    """
UPDATE l2_projection_jobs
SET status = 'failed',
    terminal_at = CAST(strftime('%s', 'now') AS REAL),
    last_error = 'projection_attempt_budget_exhausted_during_upgrade',
    updated_at = CAST(strftime('%s', 'now') AS REAL)
WHERE status = 'pending' AND attempt_count >= max_attempts
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_retry_ready
    ON l2_projection_jobs(status, next_retry_at, created_at)
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
    op.execute("DROP INDEX IF EXISTS idx_l2_projection_jobs_retry_ready")
    op.execute("ALTER TABLE l2_projection_jobs DROP COLUMN terminal_at")
    op.execute("ALTER TABLE l2_projection_jobs DROP COLUMN max_attempts")
    op.execute("ALTER TABLE l2_projection_jobs DROP COLUMN next_retry_at")
    op.execute("ALTER TABLE l2_projection_jobs DROP COLUMN lease_heartbeat_at")
    op.execute("ALTER TABLE l2_projection_jobs DROP COLUMN lease_token")


__all__ = [
    "ALTER_STATEMENTS",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
