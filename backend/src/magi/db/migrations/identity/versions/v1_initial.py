"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
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

DROP_SQL = """
DROP INDEX IF EXISTS idx_user_identity_bindings_magi_user;

DROP TABLE IF EXISTS user_identity_bindings;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
