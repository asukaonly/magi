"""runtime_notifications: index on (user_id, session_id) for read_service.py:264 purge

Revision ID: 0002_idx_notifications_user_session
Revises: 0001_initial
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op


revision = "0002_idx_notifications_user_session"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE INDEX IF NOT EXISTS idx_runtime_notifications_user_session
    ON runtime_notifications(user_id, session_id);
"""


DOWN_SQL = """
DROP INDEX IF EXISTS idx_runtime_notifications_user_session;
"""


def upgrade() -> None:
    # Inline DDL using executescript to match the 0001_initial pattern
    # (alembic op.execute only handles single statements in SQLite).
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
