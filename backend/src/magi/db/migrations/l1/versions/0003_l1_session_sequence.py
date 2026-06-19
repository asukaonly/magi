"""l1 session-local event sequence

Revision ID: 0003_l1_session_sequence
Revises: 0002_l1_event_payload
Create Date: 2026-06-19

Stores a stable per-session event order on fact_events. Retrieval can then
fetch local neighbors by indexed sequence windows instead of parsing turn_id
formats that differ between chat, benchmarks, and external integrations.
"""
from __future__ import annotations

from alembic import op


revision = "0003_l1_session_sequence"
down_revision = "0002_l1_event_payload"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l1_session_sequences (
    session_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_fact_events_session_seq
    ON fact_events(session_id, session_seq);
CREATE INDEX IF NOT EXISTS idx_fact_events_session_timestamp
    ON fact_events(session_id, timestamp, id);
"""

BACKFILL_SQL = """
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY session_id
            ORDER BY timestamp ASC, id ASC
        ) - 1 AS seq
    FROM fact_events
    WHERE session_id IS NOT NULL AND TRIM(session_id) != ''
)
UPDATE fact_events
SET session_seq = (
    SELECT ranked.seq
    FROM ranked
    WHERE ranked.id = fact_events.id
)
WHERE session_seq IS NULL
  AND id IN (SELECT id FROM ranked);

INSERT INTO l1_session_sequences(session_id, next_seq, updated_at)
SELECT
    session_id,
    COALESCE(MAX(session_seq) + 1, 0),
    CAST(strftime('%s', 'now') AS REAL)
FROM fact_events
WHERE session_id IS NOT NULL
  AND TRIM(session_id) != ''
GROUP BY session_id
ON CONFLICT(session_id) DO UPDATE SET
    next_seq = MAX(next_seq, excluded.next_seq),
    updated_at = excluded.updated_at;
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_fact_events_session_timestamp;
DROP INDEX IF EXISTS idx_fact_events_session_seq;
DROP TABLE IF EXISTS l1_session_sequences;
"""


def _fact_events_columns() -> set[str]:
    connection = op.get_bind().connection
    return {str(row[1]) for row in connection.execute("PRAGMA table_info(fact_events)")}


def upgrade() -> None:
    connection = op.get_bind().connection
    if "session_seq" not in _fact_events_columns():
        connection.execute("ALTER TABLE fact_events ADD COLUMN session_seq INTEGER")
    connection.executescript(SCHEMA_SQL)
    connection.executescript(INDEX_SQL)
    connection.executescript(BACKFILL_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
