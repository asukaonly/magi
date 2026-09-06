"""Add durable due-time retry state for source sync jobs."""

from __future__ import annotations

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind().connection
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(source_sync_jobs)").fetchall()
    }
    if "next_attempt_at" not in columns:
        op.execute(
            "ALTER TABLE source_sync_jobs "
            "ADD COLUMN next_attempt_at REAL NOT NULL DEFAULT 0"
        )
    op.execute("DROP INDEX IF EXISTS idx_source_sync_jobs_status_created")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_sync_jobs_status_due_created
        ON source_sync_jobs(status, next_attempt_at ASC, created_at ASC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_source_sync_jobs_status_due_created")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_sync_jobs_status_created
        ON source_sync_jobs(status, created_at ASC)
        """
    )
