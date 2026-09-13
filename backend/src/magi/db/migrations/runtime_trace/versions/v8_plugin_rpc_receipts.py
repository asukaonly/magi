"""Retain identities and results for explicitly confirmable plugin requests."""

from alembic import op

revision = "v8"
down_revision = "v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('''CREATE TABLE plugin_rpc_receipts (
        client_id TEXT NOT NULL, data_epoch TEXT NOT NULL, operation_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL, issued_at_ms INTEGER NOT NULL, owner TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('running','completed','uncertain')),
        http_status INTEGER, result_json TEXT, connection_id TEXT,
        PRIMARY KEY (client_id,data_epoch,operation_id)
    )''')
    op.execute("CREATE INDEX idx_plugin_rpc_connection ON plugin_rpc_receipts(connection_id)")


def downgrade() -> None:
    op.execute("DROP TABLE plugin_rpc_receipts")
