"""Separate chat session identity from creation idempotency."""

from __future__ import annotations

from alembic import op

revision = "v10"
down_revision = "v9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_session_creation_requests (
            user_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            session_id TEXT NOT NULL UNIQUE,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (user_id, idempotency_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_session_creation_requests")
