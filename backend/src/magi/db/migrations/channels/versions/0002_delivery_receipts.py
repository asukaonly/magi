"""delivery_receipts table for Phase G+3

Revision ID: 0002_delivery_receipts
Revises: 0001_initial
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op


revision = "0002_delivery_receipts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS delivery_receipts (
    receipt_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT    NOT NULL,
    run_id               TEXT    NOT NULL,
    revision             INTEGER NOT NULL DEFAULT 0,
    channel_id           TEXT    NOT NULL,
    external_message_id  TEXT,
    magi_session_id      TEXT    NOT NULL DEFAULT '',
    delivered_at_ms      INTEGER NOT NULL,
    created_at_ms        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dr_run
    ON delivery_receipts(session_id, run_id, revision);
CREATE INDEX IF NOT EXISTS idx_dr_session
    ON delivery_receipts(session_id);
"""


DOWN_SQL = """
DROP INDEX IF EXISTS idx_dr_session;
DROP INDEX IF EXISTS idx_dr_run;
DROP TABLE IF EXISTS delivery_receipts;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
