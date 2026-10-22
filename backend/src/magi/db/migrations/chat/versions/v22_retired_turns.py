"""Keep content-free receipts after irreversible chat cleanup."""
from alembic import op

revision = "v22_retired_turns"
down_revision = "v21_outbound_redaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE chat_retired_turns (
        turn_key TEXT PRIMARY KEY,
        retired_at_ms INTEGER NOT NULL
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE chat_retired_turns")
