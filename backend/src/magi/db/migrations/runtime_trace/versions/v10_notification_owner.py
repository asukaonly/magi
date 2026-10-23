"""Use the canonical local owner for the user notification center."""

from alembic import op
import sqlalchemy as sa

revision = "v10"
down_revision = "v9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE user_notifications SET user_id='local_user' WHERE user_id='default_user'")
    with op.batch_alter_table("user_notifications") as batch:
        batch.alter_column(
            "user_id", existing_type=sa.Text(), existing_nullable=False, server_default="local_user"
        )


def downgrade() -> None:
    # Ownership cannot be reversed without misattributing notifications that were
    # already canonical before the migration. Keep data assigned to its owner.
    with op.batch_alter_table("user_notifications") as batch:
        batch.alter_column(
            "user_id",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default="default_user",
        )
