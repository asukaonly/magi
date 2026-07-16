"""Persist reversible side effects of relationship corrections.

Revision ID: v14_relationship_conflict_effects
Revises: v13_stable_context_scopes
"""

from __future__ import annotations

from alembic import op

revision = "v14_relationship_conflict_effects"
down_revision = "v13_stable_context_scopes"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_relationship_conflict_effects (
    effect_id TEXT PRIMARY KEY,
    correction_id TEXT NOT NULL,
    victim_triple_id TEXT NOT NULL,
    replacement_triple_id TEXT NOT NULL,
    pre_status TEXT NOT NULL,
    pre_status_reason TEXT,
    pre_deprecated_by TEXT,
    pre_deprecated_at REAL,
    pre_valid_to REAL,
    effective_at REAL NOT NULL,
    created_at REAL NOT NULL,
    restored_at REAL,
    UNIQUE(correction_id, victim_triple_id),
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_relationship_conflict_effects_correction
    ON memory_relationship_conflict_effects(correction_id, restored_at, created_at);
CREATE INDEX IF NOT EXISTS idx_relationship_conflict_effects_victim
    ON memory_relationship_conflict_effects(victim_triple_id, restored_at);
CREATE INDEX IF NOT EXISTS idx_relationship_conflict_effects_replacement
    ON memory_relationship_conflict_effects(replacement_triple_id, restored_at);
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_relationship_conflict_effects_replacement")
    op.execute("DROP INDEX IF EXISTS idx_relationship_conflict_effects_victim")
    op.execute("DROP INDEX IF EXISTS idx_relationship_conflict_effects_correction")
    op.execute("DROP TABLE IF EXISTS memory_relationship_conflict_effects")


__all__ = ["SCHEMA_SQL", "downgrade", "schema_sql_for_fresh_database", "upgrade"]
