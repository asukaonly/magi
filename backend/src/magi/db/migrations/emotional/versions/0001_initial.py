"""emotional baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS emotional_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS emotional_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL,
    previous_mood TEXT NOT NULL,
    new_mood TEXT NOT NULL,
    mood_delta REAL NOT NULL,
    energy_delta REAL NOT NULL,
    stress_delta REAL NOT NULL,
    cause TEXT NOT NULL,
    persona_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_emotional_events_timestamp
    ON emotional_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_emotional_events_persona
    ON emotional_events(persona_id, timestamp DESC);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(
        """
        DROP TABLE IF EXISTS emotional_events;
        DROP TABLE IF EXISTS emotional_state;
        """
    )
