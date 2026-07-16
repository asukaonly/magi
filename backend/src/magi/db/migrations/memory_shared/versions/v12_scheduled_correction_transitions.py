"""Track durable activation of scheduled memory corrections.

Revision ID: v12_scheduled_correction_transitions
Revises: v11_correction_evidence_governance
"""

from __future__ import annotations

from alembic import op

revision = "v12_scheduled_correction_transitions"
down_revision = "v11_correction_evidence_governance"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE memory_corrections ADD COLUMN transition_applied_at REAL;
UPDATE memory_corrections
SET transition_applied_at = created_at
WHERE correction_kind = 'situation_changed'
  AND (effective_at IS NULL OR effective_at <= CAST(strftime('%s', 'now') AS REAL));
CREATE INDEX IF NOT EXISTS idx_memory_corrections_due_transition
    ON memory_corrections(
        correction_kind, state, transition_applied_at, effective_at
    );
"""


def upgrade() -> None:
    # Future-dated corrections were not part of a released build before this
    # revision, so no legacy projection repair is needed. Existing due changes
    # are marked applied to avoid scheduling duplicate rebuilds in dev databases.
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_corrections_due_transition")
    op.execute("ALTER TABLE memory_corrections DROP COLUMN transition_applied_at")


__all__ = ["SCHEMA_SQL", "downgrade", "upgrade"]
