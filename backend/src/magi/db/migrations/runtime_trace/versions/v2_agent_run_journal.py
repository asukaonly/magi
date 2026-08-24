"""Add canonical agent run manifests and append-only events."""

from __future__ import annotations

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE agent_run_manifests (
    run_id TEXT PRIMARY KEY,
    turn_id TEXT,
    session_id TEXT,
    user_id TEXT,
    manifest_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE agent_run_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    turn_id TEXT,
    session_id TEXT,
    user_id TEXT,
    event_type TEXT NOT NULL,
    step_index INTEGER,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(run_id, sequence),
    FOREIGN KEY(run_id) REFERENCES agent_run_manifests(run_id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_run_manifests_session_created
    ON agent_run_manifests(session_id, created_at_ms DESC);

CREATE INDEX idx_agent_run_manifests_turn
    ON agent_run_manifests(turn_id);

CREATE INDEX idx_agent_run_events_run_sequence
    ON agent_run_events(run_id, sequence);

CREATE INDEX idx_agent_run_events_turn
    ON agent_run_events(turn_id, created_at_ms);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_agent_run_events_turn;
DROP INDEX IF EXISTS idx_agent_run_events_run_sequence;
DROP INDEX IF EXISTS idx_agent_run_manifests_turn;
DROP INDEX IF EXISTS idx_agent_run_manifests_session_created;
DROP TABLE IF EXISTS agent_run_events;
DROP TABLE IF EXISTS agent_run_manifests;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
