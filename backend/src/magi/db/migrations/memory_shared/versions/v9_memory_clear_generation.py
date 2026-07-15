"""Add a persistent generation barrier for memory clears.

Revision ID: v9_memory_clear_generation
Revises: v8_quarantine_legacy_l3_insights
"""

from __future__ import annotations

from alembic import op

revision = "v9_memory_clear_generation"
down_revision = "v8_quarantine_legacy_l3_insights"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_clear_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    generation INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
INSERT OR IGNORE INTO memory_clear_state(singleton_id, generation, updated_at)
VALUES (1, 0, 0);
ALTER TABLE tom_snapshots ADD COLUMN source_generation INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_profile_projection ADD COLUMN source_generation INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_portrait_projection ADD COLUMN source_generation INTEGER NOT NULL DEFAULT 0;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("ALTER TABLE user_portrait_projection DROP COLUMN source_generation")
    op.execute("ALTER TABLE user_profile_projection DROP COLUMN source_generation")
    op.execute("ALTER TABLE tom_snapshots DROP COLUMN source_generation")
    op.execute("DROP TABLE IF EXISTS memory_clear_state")


__all__ = ["SCHEMA_SQL", "downgrade", "upgrade"]
