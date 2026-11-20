"""Keep historical reference rates used for display-currency estimates."""

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE usage_exchange_rates (
            day TEXT NOT NULL, currency TEXT NOT NULL, rate REAL NOT NULL CHECK(rate > 0),
            reference_day TEXT NOT NULL, PRIMARY KEY(day, currency)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE usage_exchange_rates")
