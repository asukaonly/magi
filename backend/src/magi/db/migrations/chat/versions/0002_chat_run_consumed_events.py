"""chat_run_consumed_events tracking table for Phase F find_dependents

Revision ID: 0002_chat_run_consumed_events
Revises: 0001_initial
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op


revision = "0002_chat_run_consumed_events"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_run_consumed_events (
    session_id     TEXT    NOT NULL,
    run_id         TEXT    NOT NULL,
    revision       INTEGER NOT NULL DEFAULT 0,
    message_id     TEXT    NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, run_id, revision, message_id)
);
CREATE INDEX IF NOT EXISTS idx_crce_message
    ON chat_run_consumed_events(session_id, message_id);
CREATE INDEX IF NOT EXISTS idx_crce_run
    ON chat_run_consumed_events(session_id, run_id, revision);
"""


DOWN_SQL = """
DROP INDEX IF EXISTS idx_crce_run;
DROP INDEX IF EXISTS idx_crce_message;
DROP TABLE IF EXISTS chat_run_consumed_events;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
