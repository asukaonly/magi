"""Persist retryable assistant-memory projection intents."""

from __future__ import annotations

from alembic import op

revision = "v5"
down_revision = "v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_assistant_memory_outbox (
            canonical_message_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            content_text TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'claimed')),
            attempt_count INTEGER NOT NULL DEFAULT 0
                CHECK (attempt_count >= 0),
            next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
            lease_token TEXT,
            lease_expires_at_ms INTEGER,
            last_error TEXT,
            updated_at_ms INTEGER NOT NULL,
            CHECK (
                (state = 'pending' AND lease_token IS NULL AND lease_expires_at_ms IS NULL)
                OR (state = 'claimed' AND lease_token IS NOT NULL AND lease_expires_at_ms IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_assistant_memory_outbox_ready
        ON chat_assistant_memory_outbox(
            state,
            next_attempt_at_ms,
            lease_expires_at_ms,
            created_at_ms,
            canonical_message_id
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_assistant_memory_outbox_session
        ON chat_assistant_memory_outbox(session_id, canonical_message_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_assistant_memory_outbox_session")
    op.execute("DROP INDEX IF EXISTS idx_chat_assistant_memory_outbox_ready")
    op.execute("DROP TABLE IF EXISTS chat_assistant_memory_outbox")
