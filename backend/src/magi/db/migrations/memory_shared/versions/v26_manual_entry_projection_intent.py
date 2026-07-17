"""Persist ownership for manual-entry projections and deletion.

Revision ID: v26_manual_entry_projection_intent
Revises: v25_daily_mood_source_events
"""

from __future__ import annotations

from alembic import op

revision = "v26_manual_entry_projection_intent"
down_revision = "v25_daily_mood_source_events"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE manual_entries
    ADD COLUMN pending_l1_event_id TEXT;
ALTER TABLE manual_entries
    ADD COLUMN pending_l1_predecessor_event_id TEXT
    CHECK(
        pending_l1_event_id IS NOT NULL
        OR pending_l1_predecessor_event_id IS NULL
    );
ALTER TABLE manual_entries
    ADD COLUMN delete_requested_at REAL;

CREATE UNIQUE INDEX idx_manual_entries_pending_l1_event
    ON manual_entries(pending_l1_event_id)
    WHERE pending_l1_event_id IS NOT NULL;
CREATE INDEX idx_manual_entries_recovery_pending
    ON manual_entries(entry_id)
    WHERE deleted_at IS NULL
      AND (
          delete_requested_at IS NOT NULL
          OR pending_l1_event_id IS NOT NULL
          OR l1_event_id IS NULL
      );
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_manual_entries_recovery_pending;
DROP INDEX IF EXISTS idx_manual_entries_pending_l1_event;
ALTER TABLE manual_entries DROP COLUMN delete_requested_at;
ALTER TABLE manual_entries DROP COLUMN pending_l1_predecessor_event_id;
ALTER TABLE manual_entries DROP COLUMN pending_l1_event_id;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v26_manual_entry_projection_intent")
    try:
        for statement in _statements(SCHEMA_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v26_manual_entry_projection_intent")
        connection.execute("RELEASE SAVEPOINT v26_manual_entry_projection_intent")
        raise
    connection.execute("RELEASE SAVEPOINT v26_manual_entry_projection_intent")


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute("""
        SELECT COUNT(*)
        FROM manual_entries
        WHERE deleted_at IS NULL
          AND (
              l1_event_id IS NULL
              OR pending_l1_event_id IS NOT NULL
              OR pending_l1_predecessor_event_id IS NOT NULL
              OR delete_requested_at IS NOT NULL
          )
        """).fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError(
            "Cannot downgrade manual-entry projection ownership while recovery is pending"
        )
    connection.execute("SAVEPOINT v26_manual_entry_projection_intent_down")
    try:
        for statement in _statements(DROP_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v26_manual_entry_projection_intent_down")
        connection.execute("RELEASE SAVEPOINT v26_manual_entry_projection_intent_down")
        raise
    connection.execute("RELEASE SAVEPOINT v26_manual_entry_projection_intent_down")


def _statements(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
