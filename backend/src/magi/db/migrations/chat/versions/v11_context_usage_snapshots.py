"""Persist context usage with accepted visible chat outcomes."""

from __future__ import annotations

from alembic import op

revision = "v11"
down_revision = "v10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_context_usage_snapshots (
            turn_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            used_tokens INTEGER NOT NULL CHECK (used_tokens > 0),
            context_window INTEGER NOT NULL CHECK (context_window > 0),
            input_capacity INTEGER NOT NULL CHECK (input_capacity > 0),
            compaction_threshold INTEGER NOT NULL CHECK (compaction_threshold > 0),
            measurement TEXT NOT NULL
                CHECK (measurement IN ('actual', 'estimated')),
            model_provider TEXT,
            model_id TEXT,
            updated_at_ms INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_context_usage_session_updated
        ON chat_context_usage_snapshots(session_id, updated_at_ms DESC, turn_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_context_usage_session_updated")
    op.execute("DROP TABLE IF EXISTS chat_context_usage_snapshots")
