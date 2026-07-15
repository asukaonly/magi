"""Index L1 evidence governed by active memory corrections.

Revision ID: v11_correction_evidence_governance
Revises: v10_relationship_version_snapshot
"""

from __future__ import annotations

from alembic import op

revision = "v11_correction_evidence_governance"
down_revision = "v10_relationship_version_snapshot"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_correction_evidence_events (
    correction_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('assertion', 'edge')),
    created_at REAL NOT NULL,
    PRIMARY KEY(correction_id, event_id),
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memory_correction_evidence_event
    ON memory_correction_evidence_events(event_id, correction_id);
INSERT OR IGNORE INTO memory_correction_evidence_events(
    correction_id, event_id, target_kind, created_at
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
), parsed_correction_evidence AS (
    SELECT normalized.correction_id,
           TRIM(CAST(evidence.value AS TEXT)) AS event_id,
           normalized.target_kind,
           normalized.created_at
    FROM normalized_correction_evidence AS normalized
    JOIN json_each(
        CASE
            WHEN json_valid(normalized.evidence_json) = 1
                THEN normalized.evidence_json
            ELSE '[]'
        END
    ) AS evidence
    WHERE evidence.type = 'text'
      AND TRIM(CAST(evidence.value AS TEXT)) != ''
), failed_correction_evidence AS (
    SELECT normalized.correction_id,
           '*' AS event_id,
           normalized.target_kind,
           normalized.created_at
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
SELECT * FROM parsed_correction_evidence
UNION ALL
SELECT * FROM failed_correction_evidence;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_correction_evidence_event")
    op.execute("DROP TABLE IF EXISTS memory_correction_evidence_events")


__all__ = ["SCHEMA_SQL", "downgrade", "upgrade"]
