"""Remove the retired orchestration identity from trace turns."""

from __future__ import annotations

from alembic import op

revision = "v4"
down_revision = "v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE trace_turns DROP COLUMN orchestration_id")


def downgrade() -> None:
    op.execute("ALTER TABLE trace_turns ADD COLUMN orchestration_id TEXT")
