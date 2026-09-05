"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_cursors (
    source_id TEXT PRIMARY KEY,
    cursor_value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS source_fingerprints (
    source_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (source_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS source_stats (
    source_id TEXT PRIMARY KEY,
    stats_json TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_fp_created
    ON source_fingerprints (source_id, created_at);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_source_fp_created;

DROP TABLE IF EXISTS source_stats;

DROP TABLE IF EXISTS source_fingerprints;

DROP TABLE IF EXISTS source_cursors;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
