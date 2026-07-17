"""Separate fail-closed evidence governance from real event identifiers.

Revision ID: v15_correction_evidence_fail_closed
Revises: v14_relationship_conflict_effects
"""

from __future__ import annotations

import sqlite3
from typing import Any

from alembic import op

revision = "v15_correction_evidence_fail_closed"
down_revision = "v14_relationship_conflict_effects"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_correction_evidence_fail_closed (
    correction_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
        ON DELETE CASCADE
);

INSERT OR IGNORE INTO memory_correction_evidence_fail_closed(
    correction_id, created_at
)
WITH raw_correction_evidence AS (
    SELECT corrections.*,
           CASE
               WHEN json_valid(corrections.before_json) = 0 THEN '__invalid_json__'
               WHEN corrections.target_kind = 'assertion' THEN
                   json_extract(corrections.before_json, '$.evidence_events')
               WHEN corrections.target_kind = 'edge' THEN
                   json_extract(corrections.before_json, '$.evidence_event_ids')
               ELSE NULL
           END AS raw_evidence
    FROM memory_corrections AS corrections
), decoded_correction_evidence AS (
    SELECT raw.*,
           CASE
               WHEN raw.raw_evidence IS NULL THEN '[]'
               WHEN json_valid(raw.raw_evidence) = 0 THEN NULL
               WHEN json_type(raw.raw_evidence) = 'text' THEN
                   json_extract(raw.raw_evidence, '$')
               ELSE raw.raw_evidence
           END AS decoded_evidence
    FROM raw_correction_evidence AS raw
), normalized_correction_evidence AS (
    SELECT decoded.*,
           CASE
               WHEN json_valid(decoded.decoded_evidence) = 1 THEN
                   CASE
                       WHEN json_type(decoded.decoded_evidence) = 'array'
                           THEN decoded.decoded_evidence
                       ELSE NULL
                   END
               ELSE NULL
           END AS evidence_json
    FROM decoded_correction_evidence AS decoded
), failed_correction_evidence AS (
    SELECT normalized.correction_id, normalized.created_at
    FROM normalized_correction_evidence AS normalized
    WHERE normalized.raw_evidence IS NOT NULL
      AND (
          normalized.evidence_json IS NULL
          OR EXISTS (
              SELECT 1
              FROM json_each(normalized.evidence_json) AS invalid_evidence
              WHERE invalid_evidence.type != 'text'
                 OR TRIM(CAST(invalid_evidence.value AS TEXT)) = ''
          )
      )
)
SELECT correction_id, created_at
FROM failed_correction_evidence;

DELETE FROM memory_correction_evidence_events
WHERE event_id = '*'
  AND correction_id IN (
      SELECT correction_id FROM memory_correction_evidence_fail_closed
  );
"""


DOWNGRADE_SQL = """
INSERT OR IGNORE INTO memory_correction_evidence_events(
    correction_id, event_id, target_kind, created_at
)
SELECT fail_closed.correction_id, '*', corrections.target_kind,
       fail_closed.created_at
FROM memory_correction_evidence_fail_closed AS fail_closed
JOIN memory_corrections AS corrections
  ON corrections.correction_id = fail_closed.correction_id;

DROP TABLE IF EXISTS memory_correction_evidence_fail_closed;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    _execute_transactionally(
        op.get_bind().connection,
        SCHEMA_SQL,
        savepoint="v15_correction_evidence_fail_closed",
    )


def downgrade() -> None:
    _execute_transactionally(
        op.get_bind().connection,
        DOWNGRADE_SQL,
        savepoint="v15_correction_evidence_fail_closed_down",
    )


def _execute_transactionally(connection: Any, script: str, *, savepoint: str) -> None:
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        pending = ""
        for line in script.splitlines():
            pending = f"{pending}{line}\n"
            if sqlite3.complete_statement(pending):
                statement = pending.strip()
                if statement:
                    connection.execute(statement)
                pending = ""
        if pending.strip():
            raise RuntimeError("Incomplete SQL in correction evidence migration")
    except Exception:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    connection.execute(f"RELEASE SAVEPOINT {savepoint}")


__all__ = [
    "DOWNGRADE_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
