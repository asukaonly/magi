"""Track plugin clear completion against the shared full-clear generation."""

from __future__ import annotations

from alembic import op

revision = "v6"
down_revision = "v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE runtime_plugin_user_content_clear_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            applied_generation INTEGER NOT NULL DEFAULT 0
                CHECK(applied_generation >= 0),
            updated_at REAL NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO runtime_plugin_user_content_clear_state(
            singleton_id,
            applied_generation,
            updated_at
        )
        SELECT
            1,
            generation,
            CAST(strftime('%s', 'now') AS REAL)
        FROM runtime_user_message_clear_state
        WHERE singleton_id = 1
        """
    )


def downgrade() -> None:
    connection = op.get_bind().connection
    row = connection.execute(
        """
        SELECT applied_generation
        FROM runtime_plugin_user_content_clear_state
        WHERE singleton_id = 1
        """
    ).fetchone()
    if row is not None and int(row[0] or 0) > 0:
        raise RuntimeError(
            "Cannot downgrade while a plugin user-content clear checkpoint exists"
        )
    connection.execute("DROP TABLE IF EXISTS runtime_plugin_user_content_clear_state")


__all__ = ["downgrade", "upgrade"]
