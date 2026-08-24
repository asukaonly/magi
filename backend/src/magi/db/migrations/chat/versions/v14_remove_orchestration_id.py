"""Remove the retired orchestration identity from chat turns."""

from __future__ import annotations

from alembic import op

revision = "v14"
down_revision = "v13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_turns DROP COLUMN orchestration_id")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_turns ADD COLUMN orchestration_id TEXT")
