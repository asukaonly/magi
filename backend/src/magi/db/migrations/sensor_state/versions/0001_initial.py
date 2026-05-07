"""sensor_state baseline schema

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
CREATE TABLE IF NOT EXISTS sensor_cursors (
    sensor_id TEXT PRIMARY KEY,
    cursor_value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sensor_fingerprints (
    sensor_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (sensor_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_sensor_fp_created
    ON sensor_fingerprints (sensor_id, created_at);

CREATE TABLE IF NOT EXISTS sensor_stats (
    sensor_id TEXT PRIMARY KEY,
    stats_json TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(
        """
        DROP TABLE IF EXISTS sensor_stats;
        DROP TABLE IF EXISTS sensor_fingerprints;
        DROP TABLE IF EXISTS sensor_cursors;
        """
    )
