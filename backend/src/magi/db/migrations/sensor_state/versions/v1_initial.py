"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
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

CREATE TABLE IF NOT EXISTS sensor_stats (
    sensor_id TEXT PRIMARY KEY,
    stats_json TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sensor_fp_created
    ON sensor_fingerprints (sensor_id, created_at);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_sensor_fp_created;

DROP TABLE IF EXISTS sensor_stats;

DROP TABLE IF EXISTS sensor_fingerprints;

DROP TABLE IF EXISTS sensor_cursors;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
