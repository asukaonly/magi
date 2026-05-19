"""daily mood aggregate

Revision ID: 0005_daily_mood_aggregate
Revises: 0004_l3_summary_essence_prose
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op

revision = "0005_daily_mood_aggregate"
down_revision = "0004_l3_summary_essence_prose"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS daily_mood_aggregate (
    day_local_date TEXT PRIMARY KEY,
    dominant_valence TEXT NOT NULL DEFAULT 'neutral',
    volatility_score REAL NOT NULL DEFAULT 0.0,
    state_curve_compact TEXT NOT NULL DEFAULT '[]',
    event_count INTEGER NOT NULL DEFAULT 0,
    computed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_mood_aggregate_computed
    ON daily_mood_aggregate(computed_at DESC);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_daily_mood_aggregate_computed;
DROP TABLE IF EXISTS daily_mood_aggregate;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
