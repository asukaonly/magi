"""Add user portrait projection.

Revision ID: 0018_user_portrait_projection
Revises: 0017_l2_experience_cover_asset
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op

revision = "0018_user_portrait_projection"
down_revision = "0017_l2_experience_cover_asset"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_portrait_projection (
    user_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'user',
    version INTEGER NOT NULL DEFAULT 1,
    world_json TEXT NOT NULL DEFAULT '{}',
    review_json TEXT NOT NULL DEFAULT '{}',
    recent_json TEXT NOT NULL DEFAULT '{}',
    prompt_summary_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    source_counts_json TEXT NOT NULL DEFAULT '{}',
    generated_by TEXT NOT NULL DEFAULT 'rule',
    generated_at REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_portrait_projection_entity
    ON user_portrait_projection(entity_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_user_portrait_projection_updated
    ON user_portrait_projection(updated_at DESC);
"""

DOWN_SQL = """
DROP INDEX IF EXISTS idx_user_portrait_projection_updated;
DROP INDEX IF EXISTS idx_user_portrait_projection_entity;
DROP TABLE IF EXISTS user_portrait_projection;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
