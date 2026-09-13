"""Durable background delivery receipts and retry scheduling."""

from alembic import op

revision = "v6"
down_revision = "v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE plugin_ingress_events ADD COLUMN delivery_epoch TEXT")
    op.execute("""
        CREATE TABLE background_delivery_receipts (
            producer_id TEXT NOT NULL, data_epoch TEXT NOT NULL,
            event_id TEXT NOT NULL, stream TEXT NOT NULL, sequence INTEGER NOT NULL,
            fingerprint TEXT NOT NULL, created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (producer_id, data_epoch, event_id),
            UNIQUE (producer_id, data_epoch, stream, sequence)
        )
    """)
    op.execute("ALTER TABLE plugin_ingress_events ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE plugin_ingress_events ADD COLUMN next_attempt_at_ms INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "CREATE INDEX idx_plugin_ingress_stream ON plugin_ingress_events(source_kind, producer, cursor_key, event_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_plugin_ingress_stream")
    op.execute("ALTER TABLE plugin_ingress_events DROP COLUMN next_attempt_at_ms")
    op.execute("ALTER TABLE plugin_ingress_events DROP COLUMN attempts")
    op.execute("DROP TABLE background_delivery_receipts")
    op.execute("ALTER TABLE plugin_ingress_events DROP COLUMN delivery_epoch")
