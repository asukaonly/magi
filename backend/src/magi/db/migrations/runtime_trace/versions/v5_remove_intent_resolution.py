"""Remove the retired semantic intent-resolution trace table."""

from __future__ import annotations

from alembic import op

revision = "v5"
down_revision = "v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE trace_intent_resolutions")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE trace_intent_resolutions (
            span_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            intent TEXT NOT NULL,
            execution_mode TEXT NOT NULL,
            route_reason TEXT,
            selected_tools_json TEXT NOT NULL,
            selected_worker_type TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_trace_intent_trace
        ON trace_intent_resolutions(trace_id)
        """
    )
