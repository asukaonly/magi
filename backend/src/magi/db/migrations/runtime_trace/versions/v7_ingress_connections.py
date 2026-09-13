"""Fence plugin ingress by its host-owned connection and content generation."""

from alembic import op

revision = "v7"
down_revision = "v6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unscoped observations cannot safely be assigned to an account.
    op.execute("DELETE FROM plugin_ingress_events")
    op.execute("ALTER TABLE plugin_ingress_events ADD COLUMN connection_id TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE plugin_ingress_events ADD COLUMN connection_epoch TEXT NOT NULL DEFAULT ''")
    op.execute("CREATE INDEX idx_plugin_ingress_connection ON plugin_ingress_events(connection_id, connection_epoch)")


def downgrade() -> None:
    op.execute("DROP INDEX idx_plugin_ingress_connection")
    op.execute("ALTER TABLE plugin_ingress_events DROP COLUMN connection_epoch")
    op.execute("ALTER TABLE plugin_ingress_events DROP COLUMN connection_id")
