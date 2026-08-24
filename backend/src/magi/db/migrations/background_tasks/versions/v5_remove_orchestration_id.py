"""Remove the retired orchestration identity from background tasks."""

from __future__ import annotations

from alembic import op

revision = "v5"
down_revision = "v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE background_tasks DROP COLUMN orchestration_id")


def downgrade() -> None:
    op.execute("ALTER TABLE background_tasks ADD COLUMN orchestration_id TEXT")
