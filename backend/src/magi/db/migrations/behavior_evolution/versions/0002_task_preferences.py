"""add task preference observations

Revision ID: 0002_task_preferences
Revises: 0001_initial
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op


revision = "0002_task_preferences"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS task_preferences (
    preference_id TEXT PRIMARY KEY,
    task_category TEXT NOT NULL,
    polarity TEXT NOT NULL,
    preference_text TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    persona_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_task_preferences_category
    ON task_preferences(persona_id, task_category, polarity);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(
        """
        DROP INDEX IF EXISTS idx_task_preferences_category;
        DROP TABLE IF EXISTS task_preferences;
        """
    )
