"""Add a durable generation boundary for destructive chat-memory clears."""

from __future__ import annotations

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE runtime_commands "
        "ADD COLUMN user_message_generation INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        """
        CREATE TABLE runtime_user_message_clear_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            generation INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO runtime_user_message_clear_state(singleton_id, generation, updated_at)
        VALUES (1, 0, CAST(strftime('%s', 'now') AS REAL))
        """
    )
    op.execute(
        """
        CREATE INDEX idx_runtime_commands_user_message_generation
        ON runtime_commands(command_type, user_message_generation)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_runtime_commands_user_message_generation")
    op.execute("DROP TABLE IF EXISTS runtime_user_message_clear_state")
    with op.batch_alter_table("runtime_commands") as batch_op:
        batch_op.drop_column("user_message_generation")
