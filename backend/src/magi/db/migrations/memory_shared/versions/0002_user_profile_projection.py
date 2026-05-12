"""user profile projection

Revision ID: 0002_user_profile_projection
Revises: 0001_initial
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op

revision = "0002_user_profile_projection"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_profile_projection (
    user_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    preferred_form_of_address TEXT NOT NULL DEFAULT '',
    real_name TEXT NOT NULL DEFAULT '',
    birth_date TEXT NOT NULL DEFAULT '',
    birth_year INTEGER,
    age_years INTEGER,
    age_as_of TEXT NOT NULL DEFAULT '',
    home_location TEXT NOT NULL DEFAULT '',
    communication_json TEXT NOT NULL DEFAULT '{}',
    identity_json TEXT NOT NULL DEFAULT '{}',
    preferences_json TEXT NOT NULL DEFAULT '{}',
    state_json TEXT NOT NULL DEFAULT '{}',
    field_sources_json TEXT NOT NULL DEFAULT '{}',
    field_conflicts_json TEXT NOT NULL DEFAULT '{}',
    completeness_score REAL NOT NULL DEFAULT 0,
    refreshed_at REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_profile_projection_entity
    ON user_profile_projection(entity_id);
CREATE INDEX IF NOT EXISTS idx_user_profile_projection_refreshed
    ON user_profile_projection(refreshed_at DESC);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_user_profile_projection_refreshed;
DROP INDEX IF EXISTS idx_user_profile_projection_entity;
DROP TABLE IF EXISTS user_profile_projection;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)