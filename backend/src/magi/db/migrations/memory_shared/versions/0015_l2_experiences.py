"""Add L2 experiences

Revision ID: 0015_l2_experiences
Revises: 0014_preference_profile_family
Create Date: 2026-06-17

Experiences are product-grade episodic memories promoted from lower-level
episode/event evidence. Episodes remain the substrate; experiences own the
user-facing identity, lifecycle, and membership boundary.
"""

from __future__ import annotations

from alembic import op

revision = "0015_l2_experiences"
down_revision = "0014_preference_profile_family"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS experiences (
    experience_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'candidate',
    title TEXT,
    time_start REAL NOT NULL,
    time_end REAL NOT NULL,
    experience_type TEXT,
    intent TEXT,
    outcome TEXT,
    magi_interpretation TEXT,
    narrative_score REAL NOT NULL DEFAULT 0.0,
    primary_entity_ids TEXT NOT NULL DEFAULT '[]',
    primary_place_ids TEXT NOT NULL DEFAULT '[]',
    primary_topic_keys TEXT NOT NULL DEFAULT '[]',
    source_episode_count INTEGER NOT NULL DEFAULT 0,
    source_event_count INTEGER NOT NULL DEFAULT 0,
    parent_experience_id TEXT,
    merged_into_experience_id TEXT,
    user_label TEXT,
    user_note TEXT,
    user_pinned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_recomputed_at REAL
);

CREATE INDEX IF NOT EXISTS idx_experiences_status_time
    ON experiences(status, time_start DESC, time_end DESC);
CREATE INDEX IF NOT EXISTS idx_experiences_parent
    ON experiences(parent_experience_id)
    WHERE parent_experience_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_experiences_merged_into
    ON experiences(merged_into_experience_id)
    WHERE merged_into_experience_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS experience_members (
    experience_id TEXT NOT NULL,
    member_type TEXT NOT NULL,
    member_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'core',
    confidence REAL NOT NULL DEFAULT 0.5,
    added_at REAL NOT NULL,
    PRIMARY KEY (experience_id, member_type, member_id)
);

CREATE INDEX IF NOT EXISTS idx_experience_members_member
    ON experience_members(member_type, member_id);

CREATE TABLE IF NOT EXISTS experience_key_events (
    experience_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    role TEXT NOT NULL,
    reason TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    added_at REAL NOT NULL,
    PRIMARY KEY (experience_id, event_id, role)
);

CREATE INDEX IF NOT EXISTS idx_experience_key_events_event
    ON experience_key_events(event_id);
"""

DOWN_SQL = """
DROP TABLE IF EXISTS experience_key_events;
DROP TABLE IF EXISTS experience_members;
DROP TABLE IF EXISTS experiences;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
