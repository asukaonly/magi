"""Persist exact user-message deletion barriers.

Revision ID: v4
Revises: v3
"""

from __future__ import annotations

from alembic import op

revision = "v4"
down_revision = "v3"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runtime_user_message_scope_blocks (
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('session', 'turn', 'message')),
    user_id TEXT NOT NULL CHECK(TRIM(user_id) != ''),
    session_id TEXT NOT NULL CHECK(TRIM(session_id) != ''),
    scope_value TEXT NOT NULL CHECK(TRIM(scope_value) != ''),
    reason TEXT NOT NULL CHECK(TRIM(reason) != ''),
    created_at REAL NOT NULL,
    PRIMARY KEY(scope_kind, user_id, session_id, scope_value)
);
CREATE INDEX IF NOT EXISTS idx_runtime_user_message_scope_blocks_lookup
    ON runtime_user_message_scope_blocks(user_id, session_id, scope_kind, scope_value);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute(
        "SELECT COUNT(*) FROM runtime_user_message_scope_blocks"
    ).fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError("Cannot downgrade while user-message deletion barriers exist")
    connection.executescript("""
        DROP INDEX IF EXISTS idx_runtime_user_message_scope_blocks_lookup;
        DROP TABLE IF EXISTS runtime_user_message_scope_blocks;
        """)


__all__ = ["SCHEMA_SQL", "downgrade", "upgrade"]
