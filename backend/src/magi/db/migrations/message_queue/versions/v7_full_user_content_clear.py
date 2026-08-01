"""Track whole-backend completion for one desktop full-clear transaction."""

from __future__ import annotations

from alembic import op

revision = "v7"
down_revision = "v6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE runtime_full_user_content_clear_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            transaction_id TEXT,
            status TEXT NOT NULL DEFAULT 'idle'
                CHECK(status IN ('idle', 'pending')),
            started_at REAL,
            CHECK(
                (status = 'idle' AND transaction_id IS NULL
                    AND started_at IS NULL)
                OR
                (status = 'pending' AND transaction_id IS NOT NULL
                    AND started_at IS NOT NULL)
            )
        )
        """)
    op.execute("""
        INSERT INTO runtime_full_user_content_clear_state(
            singleton_id,
            transaction_id,
            status,
            started_at
        ) VALUES (
            1,
            NULL,
            'idle',
            NULL
        )
        """)


def downgrade() -> None:
    connection = op.get_bind().connection
    row = connection.execute("""
        SELECT status
        FROM runtime_full_user_content_clear_state
        WHERE singleton_id = 1
        """).fetchone()
    if row is not None and str(row[0]) == "pending":
        raise RuntimeError("Cannot downgrade while a full user-content clear is pending")
    connection.execute("DROP TABLE IF EXISTS runtime_full_user_content_clear_state")


__all__ = ["downgrade", "upgrade"]
