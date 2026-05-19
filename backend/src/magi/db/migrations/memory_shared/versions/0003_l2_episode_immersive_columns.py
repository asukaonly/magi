"""l2 episode immersive columns

Revision ID: 0003_l2_episode_immersive_columns
Revises: 0002_user_profile_projection
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op

revision = "0003_l2_episode_immersive_columns"
down_revision = "0002_user_profile_projection"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE episodes ADD COLUMN slice_narrative TEXT;
ALTER TABLE episodes ADD COLUMN slice_sensory_detail TEXT;
ALTER TABLE episodes ADD COLUMN magi_standout INTEGER NOT NULL DEFAULT 0;
ALTER TABLE episodes ADD COLUMN standout_score REAL NOT NULL DEFAULT 0.0;
ALTER TABLE episodes ADD COLUMN standout_reason TEXT;
ALTER TABLE episodes ADD COLUMN representative_asset_ref TEXT;
CREATE INDEX IF NOT EXISTS idx_episodes_standout
    ON episodes(magi_standout, standout_score DESC, time_start DESC)
    WHERE magi_standout = 1 OR user_pinned = 1;
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_episodes_standout;
ALTER TABLE episodes DROP COLUMN representative_asset_ref;
ALTER TABLE episodes DROP COLUMN standout_reason;
ALTER TABLE episodes DROP COLUMN standout_score;
ALTER TABLE episodes DROP COLUMN magi_standout;
ALTER TABLE episodes DROP COLUMN slice_sensory_detail;
ALTER TABLE episodes DROP COLUMN slice_narrative;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
