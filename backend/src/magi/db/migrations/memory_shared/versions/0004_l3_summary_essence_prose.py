"""l3 summary essence prose

Revision ID: 0004_l3_summary_essence_prose
Revises: 0003_l2_episode_immersive_columns
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op

revision = "0004_l3_summary_essence_prose"
down_revision = "0003_l2_episode_immersive_columns"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE summaries ADD COLUMN narrative_style TEXT NOT NULL DEFAULT 'default';
ALTER TABLE summaries ADD COLUMN essence_prose TEXT;
CREATE INDEX IF NOT EXISTS idx_summaries_narrative_style
    ON summaries(narrative_style, summary_type, period_start DESC);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_summaries_narrative_style;
ALTER TABLE summaries DROP COLUMN essence_prose;
ALTER TABLE summaries DROP COLUMN narrative_style;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
