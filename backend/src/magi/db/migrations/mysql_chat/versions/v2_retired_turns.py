"""Keep content-free receipts after irreversible chat cleanup."""
from alembic import op

revision = "mysql_chat_v2"
down_revision = "mysql_chat_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE chat_retired_turns (
        turn_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        retired_at_ms BIGINT NOT NULL
    ) ENGINE=InnoDB""")


def downgrade() -> None:
    op.execute("DROP TABLE chat_retired_turns")
