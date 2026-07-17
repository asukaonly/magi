"""Add durable source-reference barriers for L0 temporary tactics.

Revision ID: v23_l0_tactic_source_tombstones
Revises: v22_l4_source_event_links
"""

from __future__ import annotations

from alembic import op

revision = "v23_l0_tactic_source_tombstones"
down_revision = "v22_l4_source_event_links"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE l0_forgotten_tactic_source_refs (
    source_ref TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE INDEX idx_l0_forgotten_tactic_source_refs_created
    ON l0_forgotten_tactic_source_refs(created_at, source_ref);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_l0_forgotten_tactic_source_refs_created;
DROP TABLE IF EXISTS l0_forgotten_tactic_source_refs;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v23_l0_tactic_source_tombstones")
    try:
        for statement in _statements(SCHEMA_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v23_l0_tactic_source_tombstones")
        connection.execute("RELEASE SAVEPOINT v23_l0_tactic_source_tombstones")
        raise
    connection.execute("RELEASE SAVEPOINT v23_l0_tactic_source_tombstones")


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute("SELECT COUNT(*) FROM l0_forgotten_tactic_source_refs").fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError("Cannot downgrade L0 tactic source barriers while retained data exists")
    connection.execute("SAVEPOINT v23_l0_tactic_source_tombstones_down")
    try:
        for statement in _statements(DROP_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v23_l0_tactic_source_tombstones_down")
        connection.execute("RELEASE SAVEPOINT v23_l0_tactic_source_tombstones_down")
        raise
    connection.execute("RELEASE SAVEPOINT v23_l0_tactic_source_tombstones_down")


def _statements(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
