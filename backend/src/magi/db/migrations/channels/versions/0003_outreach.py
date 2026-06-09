"""outreach outbox + delivery log tables

Revision ID: 0003_outreach
Revises: 0002_delivery_receipts
"""
from __future__ import annotations

from alembic import op


revision = "0003_outreach"
down_revision = "0002_delivery_receipts"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS outreach_outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_json     TEXT    NOT NULL,
    release_at_ms   INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',
    created_at_ms   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_outreach_outbox_due
    ON outreach_outbox (status, release_at_ms);

CREATE TABLE IF NOT EXISTS outreach_delivery_log (
    correlation_id  TEXT    NOT NULL,
    user_id         TEXT    NOT NULL,
    channel_type    TEXT    NOT NULL,
    delivered_at_ms INTEGER NOT NULL,
    PRIMARY KEY (correlation_id, channel_type)
);
CREATE INDEX IF NOT EXISTS ix_outreach_delivery_log_user
    ON outreach_delivery_log (user_id, delivered_at_ms);
"""


DOWN_SQL = """
DROP INDEX IF EXISTS ix_outreach_delivery_log_user;
DROP TABLE IF EXISTS outreach_delivery_log;
DROP INDEX IF EXISTS ix_outreach_outbox_due;
DROP TABLE IF EXISTS outreach_outbox;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
