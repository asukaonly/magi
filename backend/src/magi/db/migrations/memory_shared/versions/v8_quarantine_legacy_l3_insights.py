"""Quarantine legacy L3 insights without correction dependencies.

Revision ID: v8_quarantine_legacy_l3_insights
Revises: v7_l3_derivation_state
"""

from __future__ import annotations

from alembic import op

revision = "v8_quarantine_legacy_l3_insights"
down_revision = "v7_l3_derivation_state"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
UPDATE summaries
SET derivation_state = 'stale',
    embedding_status = 'disabled',
    embedding_profile_id = NULL,
    embedding_chunk_count = 0,
    last_embedded_at = NULL
WHERE summary_type = 'insight'
  AND derivation_state = 'current'
  AND NOT EXISTS (
      SELECT 1
      FROM memory_derivation_dependencies AS dependencies
      WHERE dependencies.artifact_kind = 'l3_insight'
        AND dependencies.artifact_id = summaries.summary_id
  );

DELETE FROM l3_summary_chunks
WHERE summary_id IN (
    SELECT summary_id FROM summaries WHERE derivation_state = 'stale'
);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    # The migration cannot distinguish a pre-existing stale insight from one
    # quarantined here, so restoring visibility would be unsafe.
    pass
