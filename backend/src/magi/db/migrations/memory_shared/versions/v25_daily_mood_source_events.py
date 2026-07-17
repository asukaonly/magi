"""Persist source-event lineage for daily mood projections.

Revision ID: v25_daily_mood_source_events
Revises: v24_entity_name_evidence
"""

from __future__ import annotations

from alembic import op

revision = "v25_daily_mood_source_events"
down_revision = "v24_entity_name_evidence"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE daily_mood_aggregate
    ADD COLUMN source_event_ids TEXT NOT NULL DEFAULT '[]';
DELETE FROM daily_mood_aggregate;
"""


DROP_SQL = """
ALTER TABLE daily_mood_aggregate DROP COLUMN source_event_ids;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v25_daily_mood_source_events")
    try:
        for statement in _statements(SCHEMA_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v25_daily_mood_source_events")
        connection.execute("RELEASE SAVEPOINT v25_daily_mood_source_events")
        raise
    connection.execute("RELEASE SAVEPOINT v25_daily_mood_source_events")


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute("SELECT COUNT(*) FROM daily_mood_aggregate").fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError("Cannot downgrade daily mood lineage while retained data exists")
    connection.execute("SAVEPOINT v25_daily_mood_source_events_down")
    try:
        for statement in _statements(DROP_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v25_daily_mood_source_events_down")
        connection.execute("RELEASE SAVEPOINT v25_daily_mood_source_events_down")
        raise
    connection.execute("RELEASE SAVEPOINT v25_daily_mood_source_events_down")


def _statements(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
