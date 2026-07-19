"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS background_tasks (
    task_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    origin_turn_id TEXT NOT NULL,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_index INTEGER NOT NULL DEFAULT 0,
    spec_json TEXT NOT NULL,
    orchestration_id TEXT,
    user_task_id TEXT,
    summary TEXT,
    result_payload_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    cancel_reason TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS background_task_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_index INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (task_id) REFERENCES background_tasks(task_id)
);

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

CREATE INDEX IF NOT EXISTS idx_bg_tasks_user_status
    ON background_tasks(user_id, status);

CREATE INDEX IF NOT EXISTS idx_bg_tasks_session
    ON background_tasks(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bg_tasks_status_created
    ON background_tasks(status, created_at);

CREATE INDEX IF NOT EXISTS idx_bg_events_task_created
    ON background_task_events(task_id, created_at);

CREATE INDEX IF NOT EXISTS idx_bg_completion_intents_state_created
    ON background_task_completion_intents(state, created_at);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_bg_completion_intents_state_created;

DROP INDEX IF EXISTS idx_bg_events_task_created;

DROP INDEX IF EXISTS idx_bg_tasks_status_created;

DROP INDEX IF EXISTS idx_bg_tasks_session;

DROP INDEX IF EXISTS idx_bg_tasks_user_status;

DROP TABLE IF EXISTS background_task_events;

DROP TABLE IF EXISTS background_task_completion_intents;

DROP TABLE IF EXISTS background_tasks;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
