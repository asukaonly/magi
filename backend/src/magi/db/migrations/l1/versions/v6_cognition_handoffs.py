"""Persist cognition delivery obligations beside their L1 facts."""

from alembic import op

revision = "v6_cognition_handoffs"
down_revision = "v5_gateway_read_indexes"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l1_cognition_handoffs (
    event_id TEXT PRIMARY KEY REFERENCES fact_events(event_id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    available_at REAL NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_l1_cognition_handoffs_ready
    ON l1_cognition_handoffs(available_at, created_at, event_id);
CREATE TRIGGER IF NOT EXISTS trg_l1_cognition_handoff_insert
AFTER INSERT ON fact_events
WHEN NEW.cognition_eligible = 1 AND NEW.deleted_at IS NULL
BEGIN
    INSERT OR IGNORE INTO l1_cognition_handoffs(event_id, created_at)
    VALUES (NEW.event_id, NEW.created_at);
END;
CREATE TRIGGER IF NOT EXISTS trg_l1_cognition_handoff_forget
AFTER UPDATE OF deleted_at ON fact_events
WHEN NEW.deleted_at IS NOT NULL
BEGIN
    DELETE FROM l1_cognition_handoffs WHERE event_id = NEW.event_id;
END;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)
    # Reconcile missing delivery only. Existing L2 jobs are acknowledged without
    # replaying completed extraction or changing immutable Claims.
    op.execute("""
        INSERT OR IGNORE INTO l1_cognition_handoffs(event_id, created_at)
        SELECT event_id, created_at FROM fact_events
        WHERE cognition_eligible = 1 AND deleted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_l1_cognition_handoff_forget")
    op.execute("DROP TRIGGER IF EXISTS trg_l1_cognition_handoff_insert")
    op.execute("DROP TABLE IF EXISTS l1_cognition_handoffs")
