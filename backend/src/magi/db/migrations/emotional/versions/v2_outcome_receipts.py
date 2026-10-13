"""Record emotional effects in the same transaction as their source receipt."""

from alembic import op

revision = "v2_outcome_receipts"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE persona_outcome_receipts (
            persona_id TEXT NOT NULL, outcome_id TEXT NOT NULL,
            effect_kind TEXT NOT NULL, user_id TEXT NOT NULL, created_at REAL NOT NULL,
            PRIMARY KEY (persona_id, outcome_id, effect_kind)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE persona_outcome_receipts")
