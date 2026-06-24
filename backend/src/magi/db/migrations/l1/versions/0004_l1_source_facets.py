"""l1 source facets

Revision ID: 0004_l1_source_facets
Revises: 0003_l1_session_sequence
Create Date: 2026-06-24

Adds a source-field index beside L1 events. The table stores exact source
facets that can be rebuilt from fact_events metadata and content.
"""

from __future__ import annotations

from alembic import op


revision = "0004_l1_source_facets"
down_revision = "0003_l1_session_sequence"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l1_source_facets (
    event_id TEXT NOT NULL,
    source TEXT NOT NULL,
    facet_name TEXT NOT NULL,
    text_value TEXT,
    normalized_text_value TEXT,
    numeric_value REAL,
    timestamp_value REAL,
    json_value TEXT,
    created_at REAL NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY(event_id) REFERENCES fact_events(event_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_l1_source_facets_event
    ON l1_source_facets(event_id);
CREATE INDEX IF NOT EXISTS idx_l1_source_facets_text
    ON l1_source_facets(source, facet_name, normalized_text_value);
CREATE INDEX IF NOT EXISTS idx_l1_source_facets_numeric
    ON l1_source_facets(source, facet_name, numeric_value);
CREATE INDEX IF NOT EXISTS idx_l1_source_facets_timestamp
    ON l1_source_facets(source, facet_name, timestamp_value);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_l1_source_facets_timestamp;
DROP INDEX IF EXISTS idx_l1_source_facets_numeric;
DROP INDEX IF EXISTS idx_l1_source_facets_text;
DROP INDEX IF EXISTS idx_l1_source_facets_event;
DROP TABLE IF EXISTS l1_source_facets;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
