"""Persist interrupted global chat-clear recovery intent."""

from __future__ import annotations

from alembic import op

revision = "v6"
down_revision = "v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_global_clear_intent (
            intent_key TEXT PRIMARY KEY
                CHECK (intent_key = 'global'),
            requested_at_ms INTEGER NOT NULL,
            session_count INTEGER NOT NULL DEFAULT 0
                CHECK (session_count >= 0)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_global_clear_intent")
