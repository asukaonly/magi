"""Track scheduled corrections cancelled by memory deletion.

Revision ID: v17_scheduled_correction_cancellation
Revises: v16_relationship_correction_reconciliation
"""

from __future__ import annotations

from alembic import op

revision = "v17_scheduled_correction_cancellation"
down_revision = "v16_relationship_correction_reconciliation"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE memory_corrections ADD COLUMN transition_cancelled_at REAL;
ALTER TABLE memory_corrections ADD COLUMN transition_cancel_reason TEXT CHECK(
    transition_cancel_reason IN ('forget_entity', 'forget_time_range')
);
DROP INDEX IF EXISTS idx_memory_corrections_due_transition;
CREATE INDEX idx_memory_corrections_due_transition
    ON memory_corrections(
        correction_kind, state, transition_applied_at,
        transition_cancelled_at, effective_at
    );
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v17_scheduled_correction_cancellation")
    try:
        connection.execute("ALTER TABLE memory_corrections ADD COLUMN transition_cancelled_at REAL")
        connection.execute("""
            ALTER TABLE memory_corrections ADD COLUMN transition_cancel_reason TEXT
            CHECK(transition_cancel_reason IN ('forget_entity', 'forget_time_range'))
            """)
        connection.execute("DROP INDEX IF EXISTS idx_memory_corrections_due_transition")
        connection.execute("""
            CREATE INDEX idx_memory_corrections_due_transition
            ON memory_corrections(
                correction_kind, state, transition_applied_at,
                transition_cancelled_at, effective_at
            )
            """)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v17_scheduled_correction_cancellation")
        connection.execute("RELEASE SAVEPOINT v17_scheduled_correction_cancellation")
        raise
    connection.execute("RELEASE SAVEPOINT v17_scheduled_correction_cancellation")


def downgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v17_scheduled_correction_cancellation_down")
    try:
        cancelled_count = int(connection.execute("""
                SELECT COUNT(*)
                FROM memory_corrections
                WHERE transition_cancelled_at IS NOT NULL
                """).fetchone()[0])
        if cancelled_count:
            raise RuntimeError(
                "Cannot downgrade scheduled correction cancellation with retained cancellations"
            )
        connection.execute("DROP INDEX IF EXISTS idx_memory_corrections_due_transition")
        connection.execute("ALTER TABLE memory_corrections DROP COLUMN transition_cancel_reason")
        connection.execute("ALTER TABLE memory_corrections DROP COLUMN transition_cancelled_at")
        connection.execute("""
            CREATE INDEX idx_memory_corrections_due_transition
            ON memory_corrections(
                correction_kind, state, transition_applied_at, effective_at
            )
            """)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v17_scheduled_correction_cancellation_down")
        connection.execute("RELEASE SAVEPOINT v17_scheduled_correction_cancellation_down")
        raise
    connection.execute("RELEASE SAVEPOINT v17_scheduled_correction_cancellation_down")


__all__ = ["SCHEMA_SQL", "downgrade", "schema_sql_for_fresh_database", "upgrade"]
