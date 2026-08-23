"""Add durable effect intent and completion records for tool invocations."""

from __future__ import annotations

from alembic import op

revision = "v4"
down_revision = "v3"
branch_labels = None
depends_on = None

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tool_effect_attempts (
    attempt_id TEXT PRIMARY KEY,
    semantic_key TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    user_id TEXT,
    session_id TEXT,
    turn_id TEXT,
    task_id TEXT,
    tool_call_id TEXT,
    tool_name TEXT NOT NULL,
    replay_policy TEXT NOT NULL,
    arguments_digest TEXT NOT NULL,
    idempotency_key_digest TEXT,
    state TEXT NOT NULL CHECK (
        state IN ('attempting', 'succeeded', 'failed_no_effect', 'uncertain')
    ),
    error_code TEXT,
    started_at REAL NOT NULL,
    finished_at REAL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_effect_attempts_semantic_state
    ON tool_effect_attempts(semantic_key, state, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_effect_attempts_scope
    ON tool_effect_attempts(scope_id, started_at DESC);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(_SCHEMA_SQL)


def downgrade() -> None:
    connection = op.get_bind().connection
    unresolved = connection.execute(
        """
        SELECT COUNT(*)
        FROM tool_effect_attempts
        WHERE state IN ('attempting', 'uncertain')
        """
    ).fetchone()
    if unresolved is not None and int(unresolved[0]) > 0:
        raise RuntimeError("Cannot downgrade tool effect ledger while outcomes are unresolved")
    connection.executescript(
        """
        DROP INDEX IF EXISTS idx_tool_effect_attempts_scope;
        DROP INDEX IF EXISTS idx_tool_effect_attempts_semantic_state;
        DROP TABLE IF EXISTS tool_effect_attempts;
        """
    )
