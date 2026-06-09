"""l0_execution_runs.trigger_json

Revision ID: 0011_l0_execution_run_trigger
Revises: 0010_kg_evidence_class
Create Date: 2026-06-05

ADR-0004 P3 (trigger seam, step 3b): persist the typed ``RunTrigger`` with the
chat execution run so it survives restart / background restore, instead of
living in chat's in-memory ``_run_triggers`` side-table.

A nullable TEXT column holding ``RunTrigger.to_dict()`` JSON — same "small
structured blob" pattern as ``attachments_json`` / ``weather_json``. Keeps the
schema homogeneous rather than breaking trigger_type / source_channel / ... into
separate columns.
"""
from __future__ import annotations

from alembic import op

revision = "0011_l0_execution_run_trigger"
down_revision = "0010_kg_evidence_class"
branch_labels = None
depends_on = None


# Named SCHEMA_SQL (not UPGRADE_SQL) so the test schema helper — which
# regex-extracts the constant by name — picks it up on a fresh DB.
SCHEMA_SQL = """
ALTER TABLE l0_execution_runs ADD COLUMN trigger_json TEXT;
"""

DROP_SQL = """
ALTER TABLE l0_execution_runs DROP COLUMN trigger_json;
"""


def upgrade() -> None:
    """Add trigger_json column — defensively.

    SQLite has no ``ADD COLUMN IF NOT EXISTS``; introspect PRAGMA table_info
    and skip the ALTER when the column is already present (e.g. a dev DB where
    it was hand-applied). Alembic still records the migration as applied.
    """
    conn = op.get_bind().connection
    cursor = conn.execute("PRAGMA table_info(l0_execution_runs)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "trigger_json" not in existing_columns:
        conn.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
