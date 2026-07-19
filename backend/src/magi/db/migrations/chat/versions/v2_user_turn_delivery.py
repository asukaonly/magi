"""Track durable delivery progress for idempotent user-message ingress."""

from __future__ import annotations

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind().connection
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_user_turn_delivery (
            turn_id TEXT PRIMARY KEY,
            projection_completed INTEGER NOT NULL DEFAULT 0,
            delivery_attempt_no INTEGER NOT NULL DEFAULT 0
                CHECK (delivery_attempt_no >= 0),
            delivery_state TEXT NOT NULL DEFAULT 'ready'
                CHECK (delivery_state IN ('ready', 'queued', 'admitted', 'terminal')),
            current_command_id INTEGER,
            runtime_envelope_json TEXT NOT NULL DEFAULT '{}',
            request_fingerprint TEXT NOT NULL DEFAULT '',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            CHECK (
                (delivery_state = 'ready' AND current_command_id IS NULL)
                OR delivery_state = 'terminal'
                OR current_command_id IS NOT NULL
            )
        )
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(chat_user_turn_delivery)"
        ).fetchall()
    }
    if "runtime_enqueued" in columns:
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
            SELECT turns.turn_id, 1, 1, '{}', '',
                   turns.created_at_ms, turns.updated_at_ms
            FROM chat_turns AS turns
            WHERE EXISTS (
                SELECT 1
                FROM chat_messages
                WHERE chat_messages.turn_id = turns.turn_id
                  AND chat_messages.role = 'user'
                  AND chat_messages.message_kind = 'user_text'
            )
            """
        )
    else:
        op.execute(
            """
            INSERT OR IGNORE INTO chat_user_turn_delivery (
                turn_id,
                projection_completed,
                delivery_attempt_no,
                delivery_state,
                current_command_id,
                runtime_envelope_json,
                request_fingerprint,
                created_at_ms,
                updated_at_ms
            )
            SELECT turns.turn_id, 1, 0, 'terminal', NULL, '{}', '',
                   turns.created_at_ms, turns.updated_at_ms
            FROM chat_turns AS turns
            WHERE EXISTS (
                SELECT 1
                FROM chat_messages
                WHERE chat_messages.turn_id = turns.turn_id
                  AND chat_messages.role = 'user'
                  AND chat_messages.message_kind = 'user_text'
            )
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_user_turn_delivery_recovery
            ON chat_user_turn_delivery(delivery_state, updated_at_ms, turn_id)
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_user_turn_delivery_recovery")
    op.execute("DROP TABLE IF EXISTS chat_user_turn_delivery")
