"""Index bounded L1 retention scans by their stable keyset."""

from alembic import op

revision = "v7_retention_scan_index"
down_revision = "v6_cognition_handoffs"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE INDEX idx_fact_events_retention_scan
    ON fact_events(retention_class, timestamp, event_id) WHERE deleted_at IS NULL;
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX idx_fact_events_retention_scan")
