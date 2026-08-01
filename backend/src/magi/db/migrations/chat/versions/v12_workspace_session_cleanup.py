"""Persist workspace session cleanup across interrupted global data clears."""

from __future__ import annotations

from alembic import op

revision = "v12"
down_revision = "v11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_workspace_session_cleanup (
            workspace_path TEXT NOT NULL,
            session_id TEXT COLLATE NOCASE NOT NULL,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (workspace_path, session_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_workspace_session_cleanup")
