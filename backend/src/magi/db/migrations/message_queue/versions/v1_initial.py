"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
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
    delivery_attempt_no INTEGER NOT NULL DEFAULT 0
        CHECK (delivery_attempt_no >= 0),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

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

CREATE TABLE IF NOT EXISTS runtime_user_message_idempotency (
    correlation_id TEXT PRIMARY KEY,
    payload_fingerprint TEXT NOT NULL,
    current_attempt_no INTEGER NOT NULL
        CHECK (current_attempt_no >= 0),
    current_command_id INTEGER NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_user_message_scope_blocks (
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('session', 'turn', 'message')),
    user_id TEXT NOT NULL CHECK(TRIM(user_id) != ''),
    session_id TEXT NOT NULL CHECK(TRIM(session_id) != ''),
    scope_value TEXT NOT NULL CHECK(TRIM(scope_value) != ''),
    reason TEXT NOT NULL CHECK(TRIM(reason) != ''),
    created_at REAL NOT NULL,
    PRIMARY KEY(scope_kind, user_id, session_id, scope_value)
);

CREATE INDEX IF NOT EXISTS idx_runtime_commands_status_created
    ON runtime_commands(status, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_runtime_commands_type_status_created
    ON runtime_commands(command_type, status, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_runtime_command_rollups_bucket
    ON runtime_command_rollups(granularity, bucket_start);

CREATE INDEX IF NOT EXISTS idx_runtime_user_message_scope_blocks_lookup
    ON runtime_user_message_scope_blocks(user_id, session_id, scope_kind, scope_value);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_runtime_user_message_scope_blocks_lookup;

DROP INDEX IF EXISTS idx_runtime_command_rollups_bucket;

DROP INDEX IF EXISTS idx_runtime_commands_type_status_created;

DROP INDEX IF EXISTS idx_runtime_commands_status_created;

DROP TABLE IF EXISTS runtime_command_rollups;

DROP TABLE IF EXISTS runtime_user_message_idempotency;

DROP TABLE IF EXISTS runtime_user_message_scope_blocks;

DROP TABLE IF EXISTS runtime_commands;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
