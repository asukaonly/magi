"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS task_interactions (
    task_id TEXT PRIMARY KEY,
    task_category TEXT NOT NULL,
    timestamp REAL NOT NULL,
    clarification_count INTEGER NOT NULL,
    confirmation_count INTEGER NOT NULL,
    correction_count INTEGER NOT NULL,
    satisfaction TEXT NOT NULL,
    task_complexity REAL NOT NULL,
    task_duration REAL NOT NULL,
    accepted INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    persona_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS category_statistics (
    category TEXT PRIMARY KEY,
    total_tasks INTEGER NOT NULL,
    accepted_tasks INTEGER NOT NULL,
    avg_clarifications REAL NOT NULL,
    avg_confirmations REAL NOT NULL,
    avg_corrections REAL NOT NULL,
    avg_satisfaction REAL NOT NULL,
    avg_complexity REAL NOT NULL,
    cautious_score REAL NOT NULL,
    impatient_score REAL NOT NULL,
    dense_score REAL NOT NULL,
    updated_at REAL NOT NULL,
    persona_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS behavior_profiles (
    task_category TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    persona_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_task_interactions_category
    ON task_interactions(task_category);

CREATE INDEX IF NOT EXISTS idx_task_interactions_persona
    ON task_interactions(persona_id, task_category);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_task_interactions_persona;

DROP INDEX IF EXISTS idx_task_interactions_category;

DROP TABLE IF EXISTS behavior_profiles;

DROP TABLE IF EXISTS category_statistics;

DROP TABLE IF EXISTS task_interactions;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
