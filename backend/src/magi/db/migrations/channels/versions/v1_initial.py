"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
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

CREATE TABLE IF NOT EXISTS channel_binding_settings (
    channel_type      TEXT    NOT NULL,
    external_user_id  TEXT    NOT NULL,
    auto_approve      INTEGER NOT NULL DEFAULT 0,
    updated_at_ms     INTEGER NOT NULL,
    PRIMARY KEY (channel_type, external_user_id)
);

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

CREATE TABLE IF NOT EXISTS outreach_outbox (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id     TEXT    NOT NULL,
    channel_scope      TEXT    NOT NULL,
    intent_fingerprint TEXT    NOT NULL,
    intent_json        TEXT    NOT NULL,
    release_at_ms      INTEGER NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending',
    created_at_ms      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_delivery_log (
    correlation_id  TEXT    NOT NULL,
    user_id         TEXT    NOT NULL,
    channel_type    TEXT    NOT NULL,
    delivered_at_ms INTEGER NOT NULL,
    PRIMARY KEY (correlation_id, channel_type)
);

CREATE INDEX IF NOT EXISTS idx_csm_session
    ON channel_session_mappings(magi_session_id);

CREATE INDEX IF NOT EXISTS idx_dr_run
    ON delivery_receipts(session_id, run_id, revision);

CREATE INDEX IF NOT EXISTS idx_dr_session
    ON delivery_receipts(session_id);

CREATE INDEX IF NOT EXISTS ix_outreach_outbox_due
    ON outreach_outbox (status, release_at_ms);

CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_outbox_identity
    ON outreach_outbox (correlation_id, channel_scope);

CREATE INDEX IF NOT EXISTS ix_outreach_delivery_log_user
    ON outreach_delivery_log (user_id, delivered_at_ms);
"""

DROP_SQL = """
DROP INDEX IF EXISTS ix_outreach_delivery_log_user;

DROP INDEX IF EXISTS ix_outreach_outbox_due;

DROP INDEX IF EXISTS uq_outreach_outbox_identity;

DROP INDEX IF EXISTS idx_dr_session;

DROP INDEX IF EXISTS idx_dr_run;

DROP INDEX IF EXISTS idx_csm_session;

DROP TABLE IF EXISTS outreach_delivery_log;

DROP TABLE IF EXISTS outreach_outbox;

DROP TABLE IF EXISTS delivery_receipts;

DROP TABLE IF EXISTS channel_binding_settings;

DROP TABLE IF EXISTS channel_relay_state;

DROP TABLE IF EXISTS channel_notification_cursors;

DROP TABLE IF EXISTS channel_session_mappings;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
