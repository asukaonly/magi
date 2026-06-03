"""channels baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channel_session_mappings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_type      TEXT    NOT NULL,
    external_chat_id  TEXT    NOT NULL,
    magi_session_id   TEXT    NOT NULL,
    magi_user_id      TEXT    NOT NULL,
    is_group          INTEGER NOT NULL DEFAULT 0,
    created_at_ms     INTEGER NOT NULL,
    last_active_at_ms INTEGER NOT NULL,
    metadata_json     TEXT    NOT NULL DEFAULT '{}',
    UNIQUE(channel_type, external_chat_id)
);
CREATE INDEX IF NOT EXISTS idx_csm_session
    ON channel_session_mappings(magi_session_id);

CREATE TABLE IF NOT EXISTS channel_notification_cursors (
    channel_type      TEXT    NOT NULL,
    external_chat_id  TEXT    NOT NULL,
    last_notification_id INTEGER NOT NULL DEFAULT 0,
    updated_at_ms     INTEGER NOT NULL,
    PRIMARY KEY (channel_type, external_chat_id)
);

CREATE TABLE IF NOT EXISTS channel_relay_state (
    state_key       TEXT    PRIMARY KEY,
    value_integer   INTEGER NOT NULL DEFAULT 0,
    updated_at_ms   INTEGER NOT NULL
);

-- Phase H+2: per-binding settings (the "外部渠道免审批" toggle the
-- user can flip from desktop Settings). Keyed by
-- (channel_type, external_user_id) — one row per WeChat OpenID /
-- Telegram user_id — so the same person on different channels can
-- have different policies.
CREATE TABLE IF NOT EXISTS channel_binding_settings (
    channel_type      TEXT    NOT NULL,
    external_user_id  TEXT    NOT NULL,
    auto_approve      INTEGER NOT NULL DEFAULT 0,
    updated_at_ms     INTEGER NOT NULL,
    PRIMARY KEY (channel_type, external_user_id)
);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(
        """
        DROP TABLE IF EXISTS channel_relay_state;
        DROP TABLE IF EXISTS channel_notification_cursors;
        DROP TABLE IF EXISTS channel_session_mappings;
        """
    )
