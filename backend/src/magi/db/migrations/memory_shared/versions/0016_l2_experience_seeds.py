"""Add L2 experience seeds

Revision ID: 0016_l2_experience_seeds
Revises: 0015_l2_experiences
Create Date: 2026-06-18

Experience seeds are durable candidates that explain why a set of episode
evidence might become a user-facing experience. They prevent generic episode
clusters from being promoted without a meaningful trigger.
"""

from __future__ import annotations

from alembic import op

revision = "0016_l2_experience_seeds"
down_revision = "0015_l2_experiences"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
ALTER TABLE experiences ADD COLUMN source_seed_id TEXT;

CREATE INDEX IF NOT EXISTS idx_experiences_source_seed
    ON experiences(source_seed_id)
    WHERE source_seed_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS experience_seeds (
    seed_id TEXT PRIMARY KEY,
    seed_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    title TEXT,
    description TEXT,
    anchor_entity_ids TEXT NOT NULL DEFAULT '[]',
    anchor_place_ids TEXT NOT NULL DEFAULT '[]',
    anchor_topic_keys TEXT NOT NULL DEFAULT '[]',
    time_start REAL,
    time_end REAL,
    confidence REAL NOT NULL DEFAULT 0.0,
    created_by TEXT NOT NULL DEFAULT 'system',
    source_ref_type TEXT,
    source_ref_id TEXT,
    promoted_experience_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_evaluated_at REAL
);

CREATE INDEX IF NOT EXISTS idx_experience_seeds_status_time
    ON experience_seeds(status, time_start DESC, time_end DESC);

CREATE INDEX IF NOT EXISTS idx_experience_seeds_source_ref
    ON experience_seeds(source_ref_type, source_ref_id)
    WHERE source_ref_type IS NOT NULL AND source_ref_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS experience_seed_evidence (
    seed_id TEXT NOT NULL,
    ref_type TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'support',
    confidence REAL NOT NULL DEFAULT 0.5,
    reason TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (seed_id, ref_type, ref_id, role)
);

CREATE INDEX IF NOT EXISTS idx_experience_seed_evidence_ref
    ON experience_seed_evidence(ref_type, ref_id);
"""

DOWN_SQL = """
DROP TABLE IF EXISTS experience_seed_evidence;
DROP TABLE IF EXISTS experience_seeds;
DROP INDEX IF EXISTS idx_experiences_source_seed;
ALTER TABLE experiences DROP COLUMN source_seed_id;
"""


def upgrade() -> None:
    """Add seed tables and source_seed_id defensively."""

    conn = op.get_bind().connection
    cursor = conn.execute("PRAGMA table_info(experiences)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "source_seed_id" not in existing_columns:
        conn.execute("ALTER TABLE experiences ADD COLUMN source_seed_id TEXT")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_experiences_source_seed
            ON experiences(source_seed_id)
            WHERE source_seed_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS experience_seeds (
            seed_id TEXT PRIMARY KEY,
            seed_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate',
            title TEXT,
            description TEXT,
            anchor_entity_ids TEXT NOT NULL DEFAULT '[]',
            anchor_place_ids TEXT NOT NULL DEFAULT '[]',
            anchor_topic_keys TEXT NOT NULL DEFAULT '[]',
            time_start REAL,
            time_end REAL,
            confidence REAL NOT NULL DEFAULT 0.0,
            created_by TEXT NOT NULL DEFAULT 'system',
            source_ref_type TEXT,
            source_ref_id TEXT,
            promoted_experience_id TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_evaluated_at REAL
        );

        CREATE INDEX IF NOT EXISTS idx_experience_seeds_status_time
            ON experience_seeds(status, time_start DESC, time_end DESC);

        CREATE INDEX IF NOT EXISTS idx_experience_seeds_source_ref
            ON experience_seeds(source_ref_type, source_ref_id)
            WHERE source_ref_type IS NOT NULL AND source_ref_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS experience_seed_evidence (
            seed_id TEXT NOT NULL,
            ref_type TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'support',
            confidence REAL NOT NULL DEFAULT 0.5,
            reason TEXT,
            created_at REAL NOT NULL,
            PRIMARY KEY (seed_id, ref_type, ref_id, role)
        );

        CREATE INDEX IF NOT EXISTS idx_experience_seed_evidence_ref
            ON experience_seed_evidence(ref_type, ref_id);
        """
    )


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
