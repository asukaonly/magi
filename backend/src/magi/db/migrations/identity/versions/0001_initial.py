"""identity baseline schema

Creates the ``user_identity_bindings`` table — the single source of
truth for ``(channel_type, external_user_id) -> MagiUserID`` bindings.

See ``docs/identity-architecture.md`` §6.4 for the schema design.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-02
"""
from __future__ import annotations

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_identity_bindings (
    channel_type      TEXT    NOT NULL,
    external_user_id  TEXT    NOT NULL,
    magi_user_id      TEXT    NOT NULL,
    created_at_ms     INTEGER NOT NULL,
    last_seen_at_ms   INTEGER NOT NULL,
    UNIQUE(channel_type, external_user_id)
);
CREATE INDEX IF NOT EXISTS idx_user_identity_bindings_magi_user
    ON user_identity_bindings(magi_user_id);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(
        """
        DROP INDEX IF EXISTS idx_user_identity_bindings_magi_user;
        DROP TABLE IF EXISTS user_identity_bindings;
        """
    )
