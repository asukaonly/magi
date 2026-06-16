"""Drop vestigial privacy_scope columns

Revision ID: 0012_drop_privacy_scope
Revises: 0011_l0_execution_run_trigger
Create Date: 2026-06-15

privacy_scope was reserved in the 0001 baseline (NOT NULL DEFAULT 'private')
on knowledge_graph / entity_facets / tom_trait_assertions / episodes but was
never read or set beyond the default — the live evidence-governance need is
served by evidence_class instead. Drop the dead columns. SQLite 3.35+ supports
DROP COLUMN; only the default value ever existed, so no data is lost.

Named SCHEMA_SQL so the test schema helper (tests/_shared/memory_schema.py)
applies it (via regex) after the 0001 CREATE on a fresh test DB.
"""

from __future__ import annotations

from alembic import op

revision = "0012_drop_privacy_scope"
down_revision = "0011_l0_execution_run_trigger"
branch_labels = None
depends_on = None

_TABLES = ("knowledge_graph", "entity_facets", "tom_trait_assertions", "episodes")

SCHEMA_SQL = """
ALTER TABLE knowledge_graph DROP COLUMN privacy_scope;
ALTER TABLE entity_facets DROP COLUMN privacy_scope;
ALTER TABLE tom_trait_assertions DROP COLUMN privacy_scope;
ALTER TABLE episodes DROP COLUMN privacy_scope;
"""

DROP_SQL = """
ALTER TABLE knowledge_graph ADD COLUMN privacy_scope TEXT NOT NULL DEFAULT 'private';
ALTER TABLE entity_facets ADD COLUMN privacy_scope TEXT NOT NULL DEFAULT 'private';
ALTER TABLE tom_trait_assertions ADD COLUMN privacy_scope TEXT NOT NULL DEFAULT 'private';
ALTER TABLE episodes ADD COLUMN privacy_scope TEXT NOT NULL DEFAULT 'private';
"""


def upgrade() -> None:
    conn = op.get_bind().connection
    for table in _TABLES:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in cursor.fetchall()}
        if "privacy_scope" in cols:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN privacy_scope")


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
