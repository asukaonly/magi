"""Persist bounded retention scan progress across maintenance runs."""

from alembic import op

revision = "v55_retention_scan_cursors"
down_revision = "v54_preference_exclusions"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE memory_retention_scan_cursors (
    layer TEXT PRIMARY KEY CHECK (layer IN ('l1', 'l3')),
    cutoff_at REAL,
    position_at REAL,
    position_id TEXT,
    revision INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    CHECK ((cutoff_at IS NULL AND position_at IS NULL AND position_id IS NULL)
        OR (cutoff_at IS NOT NULL AND position_at IS NOT NULL AND position_id IS NOT NULL))
);
CREATE INDEX idx_summaries_retention_scan
    ON summaries(derivation_state, period_end, summary_id);
"""


def upgrade() -> None:
    for statement in SCHEMA_SQL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX idx_summaries_retention_scan")
    op.execute("DROP TABLE memory_retention_scan_cursors")
