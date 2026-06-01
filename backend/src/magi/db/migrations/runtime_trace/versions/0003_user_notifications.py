"""user_notifications durable table

Revision ID: 0003_user_notifications
Revises: 0002_idx_notifications_user_session
Create Date: 2026-05-31

Durable per-user notification feed (read/unread/actioned/dismissed),
deliberately separate from the ephemeral runtime_notifications transport
table. Shares the runtime_trace SQLite DB and migration chain.
"""
from __future__ import annotations

from alembic import op


revision = "0003_user_notifications"
down_revision = "0002_idx_notifications_user_session"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default_user',
    kind TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'unread',
    created_at_ms INTEGER NOT NULL,
    read_at_ms INTEGER,
    actioned_at_ms INTEGER,
    dismissed_at_ms INTEGER,
    dismiss_kind TEXT
);
CREATE INDEX IF NOT EXISTS idx_user_notifications_feed
    ON user_notifications(user_id, created_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_user_notifications_dedup
    ON user_notifications(user_id, kind, dedupe_key);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS user_notifications;
"""


def upgrade() -> None:
    # Inline DDL using executescript to match the 0001_initial pattern
    # (alembic op.execute only handles single statements in SQLite).
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
