"""Own indexes used by native L1 readers in the migration chain."""
from alembic import op

revision = "v5_gateway_read_indexes"
down_revision = "v4_history_import_deletion_privacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_fact_events_deleted_at ON fact_events(deleted_at) WHERE deleted_at IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_fact_events_deleted_at")
