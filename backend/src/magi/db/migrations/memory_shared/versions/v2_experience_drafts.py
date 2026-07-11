"""Add guided experience drafts and durable chapters.

Revision ID: v2_experience_drafts
Revises: v1
"""

from alembic import op


revision = "v2_experience_drafts"
down_revision = "v1"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS experience_drafts (
    draft_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'editing',
    query_text TEXT NOT NULL,
    title TEXT NOT NULL,
    one_sentence_review TEXT NOT NULL,
    time_start REAL NOT NULL,
    time_end REAL NOT NULL,
    chapters_json TEXT NOT NULL DEFAULT '[]',
    possible_evidence_json TEXT NOT NULL DEFAULT '[]',
    excluded_evidence_json TEXT NOT NULL DEFAULT '[]',
    created_experience_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS experience_chapters (
    experience_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    time_start REAL,
    time_end REAL,
    episode_ids_json TEXT NOT NULL DEFAULT '[]',
    event_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (experience_id, chapter_id)
);

CREATE INDEX IF NOT EXISTS idx_experience_drafts_status_updated
    ON experience_drafts(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_experience_chapters_experience_position
    ON experience_chapters(experience_id, position);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_experience_chapters_experience_position;
DROP INDEX IF EXISTS idx_experience_drafts_status_updated;
DROP TABLE IF EXISTS experience_chapters;
DROP TABLE IF EXISTS experience_drafts;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
