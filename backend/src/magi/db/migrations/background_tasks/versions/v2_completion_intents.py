"""Persist recoverable background-task completion intents."""

from __future__ import annotations

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
CREATE TABLE IF NOT EXISTS background_task_completion_intents (
    task_id TEXT NOT NULL,
    attempt_index INTEGER NOT NULL,
    task_json TEXT NOT NULL,
    intent_json TEXT,
    composed_body TEXT,
    claim_token TEXT,
    claimed_at REAL,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'processing', 'handled', 'discarded')),
    created_at REAL NOT NULL,
    handled_at REAL,
    PRIMARY KEY (task_id, attempt_index)
);

CREATE INDEX IF NOT EXISTS idx_bg_completion_intents_state_created
    ON background_task_completion_intents(state, created_at);
"""

DOWNGRADE_SQL = """
DROP INDEX IF EXISTS idx_bg_completion_intents_state_created;
DROP TABLE IF EXISTS background_task_completion_intents;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(UPGRADE_SQL)


def downgrade() -> None:
    connection = op.get_bind().connection
    pending = connection.execute(
        """
        SELECT COUNT(*)
        FROM background_task_completion_intents
        WHERE state IN ('pending', 'processing')
        """
    ).fetchone()
    if pending is not None and int(pending[0]) > 0:
        raise RuntimeError(
            "Cannot downgrade background completion intents while delivery is pending"
        )
    connection.executescript(DOWNGRADE_SQL)
