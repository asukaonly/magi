"""batch baseline schema

Creates the ``batch_job`` and ``batch_item`` tables — the manifest for the
batch orchestrator. ``handler_config``/``seed_spec``/``input``/``result``/
``review_decision`` are opaque JSON text blobs the engine never interprets.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-03
"""
from __future__ import annotations

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS batch_job (
    job_id                TEXT    PRIMARY KEY,
    title                 TEXT    NOT NULL,
    owner                 TEXT    NOT NULL,
    origin_session_id     TEXT    NOT NULL DEFAULT '',
    origin_turn_id        TEXT    NOT NULL DEFAULT '',
    handler_ref           TEXT    NOT NULL,
    handler_config        TEXT    NOT NULL DEFAULT '{}',
    seed_spec             TEXT    NOT NULL DEFAULT '{}',
    status                TEXT    NOT NULL,
    batch_size            INTEGER NOT NULL DEFAULT 15,
    concurrency           INTEGER NOT NULL DEFAULT 1,
    max_attempts          INTEGER NOT NULL DEFAULT 3,
    reconcile_rounds_max  INTEGER NOT NULL DEFAULT 2,
    created_at_ms         INTEGER NOT NULL,
    updated_at_ms         INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_item (
    job_id               TEXT    NOT NULL,
    item_id              TEXT    NOT NULL,
    input                TEXT    NOT NULL DEFAULT '{}',
    status               TEXT    NOT NULL,
    attempts             INTEGER NOT NULL DEFAULT 0,
    result               TEXT,
    error                TEXT,
    review_reason        TEXT,
    review_decision      TEXT,
    lease_owner          TEXT,
    lease_expires_at_ms  INTEGER,
    updated_at_ms        INTEGER NOT NULL,
    PRIMARY KEY (job_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_batch_item_job_status
    ON batch_item(job_id, status);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(
        """
        DROP INDEX IF EXISTS idx_batch_item_job_status;
        DROP TABLE IF EXISTS batch_item;
        DROP TABLE IF EXISTS batch_job;
        """
    )
