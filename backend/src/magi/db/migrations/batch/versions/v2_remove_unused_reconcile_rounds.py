"""Remove the retired inline driver's reconciliation limit."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'v2'
down_revision = 'v1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("batch_job") as batch_op:
        batch_op.drop_column("reconcile_rounds_max")


def downgrade() -> None:
    with op.batch_alter_table("batch_job") as batch_op:
        batch_op.add_column(
            sa.Column("reconcile_rounds_max", sa.Integer(), nullable=False, server_default="2")
        )
