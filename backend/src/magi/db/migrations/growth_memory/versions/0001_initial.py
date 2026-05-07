"""growth_memory baseline schema

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
CREATE TABLE IF NOT EXISTS milestones (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    timestamp REAL NOT NULL,
    metadata TEXT NOT NULL,
    persona_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_milestones_timestamp
    ON milestones(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_milestones_persona
    ON milestones(persona_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS relationships (
    user_id TEXT PRIMARY KEY,
    depth REAL NOT NULL,
    first_interaction REAL NOT NULL,
    last_interaction REAL NOT NULL,
    total_interactions INTEGER NOT NULL,
    interaction_types TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    trust_level REAL NOT NULL,
    notes TEXT NOT NULL,
    updated_at REAL NOT NULL,
    persona_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_relationships_updated
    ON relationships(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_relationships_persona
    ON relationships(persona_id, user_id);

CREATE TABLE IF NOT EXISTS personality_evolution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    aspect TEXT NOT NULL,
    previous_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS growth_statistics (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(
        """
        DROP TABLE IF EXISTS growth_statistics;
        DROP TABLE IF EXISTS personality_evolution;
        DROP TABLE IF EXISTS relationships;
        DROP TABLE IF EXISTS milestones;
        """
    )
