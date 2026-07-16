"""Track durable delivery progress for idempotent user-message ingress."""

from __future__ import annotations

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_user_turn_delivery (
            turn_id TEXT PRIMARY KEY,
            projection_completed INTEGER NOT NULL DEFAULT 0,
            runtime_enqueued INTEGER NOT NULL DEFAULT 0,
            runtime_envelope_json TEXT NOT NULL DEFAULT '{}',
            request_fingerprint TEXT NOT NULL DEFAULT '',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT OR IGNORE INTO chat_user_turn_delivery (
            turn_id,
            projection_completed,
            runtime_enqueued,
            runtime_envelope_json,
            request_fingerprint,
            created_at_ms,
            updated_at_ms
        )
        SELECT turn_id, 1, 1, '{}', '', created_at_ms, updated_at_ms
        FROM chat_turns
        WHERE EXISTS (
            SELECT 1
            FROM chat_messages
            WHERE chat_messages.turn_id = chat_turns.turn_id
              AND chat_messages.role = 'user'
              AND chat_messages.message_kind = 'user_text'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_user_turn_delivery")
