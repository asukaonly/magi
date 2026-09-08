"""Own indexes used by native memory readers in the migration chain."""
from alembic import op

revision = "v53_gateway_read_indexes"
down_revision = "v52_entity_identity_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_status_updated ON knowledge_graph(status, updated_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tom_assertions_updated ON tom_trait_assertions(updated_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_summaries_updated ON summaries(updated_at DESC)")


def downgrade() -> None:
    for name in ("idx_kg_status_updated", "idx_tom_assertions_updated", "idx_summaries_updated"):
        op.execute(f"DROP INDEX IF EXISTS {name}")
