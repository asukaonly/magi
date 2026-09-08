"""Retain content-free schedule creation receipts after execution or deletion."""

from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS schedule_creation_receipts (
            schedule_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS schedule_creation_receipts")
