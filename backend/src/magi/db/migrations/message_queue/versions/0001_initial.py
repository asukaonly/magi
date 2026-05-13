"""message_queue baseline schema

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
CREATE TABLE IF NOT EXISTS runtime_commands (
    command_id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    claimed_by TEXT,
    claimed_at REAL,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_commands_status_created
    ON runtime_commands(status, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_runtime_commands_type_status_created
    ON runtime_commands(command_type, status, created_at ASC);

CREATE TABLE IF NOT EXISTS runtime_command_rollups (
    granularity TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    command_type TEXT NOT NULL,
    status TEXT NOT NULL,
    commands INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    last_rolled_up_at REAL NOT NULL,
    PRIMARY KEY (granularity, bucket_start, command_type, status)
);
CREATE INDEX IF NOT EXISTS idx_runtime_command_rollups_bucket
    ON runtime_command_rollups(granularity, bucket_start);
"""

DROP_SQL = """
DROP TABLE IF EXISTS runtime_command_rollups;
DROP TABLE IF EXISTS runtime_commands;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
