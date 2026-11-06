"""Retain the semantic source of bounded delivery history without its payload."""
from alembic import op

revision = "v13"
down_revision = "v12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE plugin_ingress_events ADD COLUMN source_type TEXT")
    op.execute("CREATE INDEX idx_ingress_source_history ON plugin_ingress_events(connection_id, source_type, event_id)")


def downgrade() -> None:
    op.execute("DROP INDEX idx_ingress_source_history")
    op.execute("ALTER TABLE plugin_ingress_events DROP COLUMN source_type")
