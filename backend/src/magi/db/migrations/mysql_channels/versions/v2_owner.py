"""Bind external channel state to one logical center."""

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS magi_channels_owner (
        singleton_id INTEGER NOT NULL PRIMARY KEY,
        center_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        CONSTRAINT ck_channels_owner_singleton CHECK(singleton_id=1)
    ) ENGINE=InnoDB""")


def downgrade() -> None:
    raise RuntimeError("External storage ownership cannot be silently removed")
