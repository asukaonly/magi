"""Commit post-turn L0 receipts with their attention checkpoint."""

from alembic import op

revision = "v56_l0_outcome_receipts"
down_revision = "v55_retention_scan_cursors"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l0_outcome_receipts (
    outcome_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES l0_sessions(session_id) ON DELETE CASCADE,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l0_outcome_receipts_session ON l0_outcome_receipts(session_id);
CREATE TABLE IF NOT EXISTS post_turn_effect_receipts (
    effect_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def upgrade() -> None:
    for statement in SCHEMA_SQL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE post_turn_effect_receipts")
    op.execute("DROP TABLE l0_outcome_receipts")
