"""Prevent individually cleared chat messages from being recreated."""

from __future__ import annotations

from alembic import op

revision = "v8"
down_revision = "v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_cleared_message_scopes (
            session_id TEXT COLLATE NOCASE NOT NULL,
            message_id TEXT COLLATE NOCASE NOT NULL,
            cleared_at_ms INTEGER NOT NULL,
            PRIMARY KEY (session_id, message_id)
        )
        """
    )
    op.execute(
        """
        INSERT OR IGNORE INTO chat_cleared_message_scopes(
            session_id,
            message_id,
            cleared_at_ms
        )
        SELECT
            session_id,
            message_id,
            CAST(strftime('%s', 'now') AS INTEGER) * 1000
        FROM chat_messages
        WHERE is_visible = 0
          AND content_text = ''
          AND TRIM(payload_json) = '{}'
          AND replaces_message_id IS NULL
          AND replaced_by_message_id IS NULL
          AND persona_id IS NULL
          AND reply_to_message_id IS NULL
          AND label_json IS NULL
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_chat_messages_reject_cleared_message
        BEFORE INSERT ON chat_messages
        WHEN EXISTS (
            SELECT 1
            FROM chat_cleared_message_scopes AS cleared
            WHERE cleared.session_id = NEW.session_id COLLATE NOCASE
              AND cleared.message_id = NEW.message_id COLLATE NOCASE
        )
        BEGIN
            SELECT RAISE(ABORT, 'chat message was cleared');
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chat_messages_reject_cleared_message")
    op.execute("DROP TABLE IF EXISTS chat_cleared_message_scopes")
