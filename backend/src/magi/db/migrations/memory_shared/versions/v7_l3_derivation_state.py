"""Add explicit lifecycle state for correction-sensitive L3 insights.

Revision ID: v7_l3_derivation_state
Revises: v6_relationship_governance_slots
"""

from __future__ import annotations

from alembic import op

revision = "v7_l3_derivation_state"
down_revision = "v6_relationship_governance_slots"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE summaries ADD COLUMN derivation_state TEXT NOT NULL DEFAULT 'current'
    CHECK(derivation_state IN ('current', 'stale', 'retired'));
CREATE INDEX IF NOT EXISTS idx_summaries_derivation_state
    ON summaries(derivation_state, summary_type, updated_at DESC);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_summaries_derivation_state;
ALTER TABLE summaries DROP COLUMN derivation_state;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
