"""Add source evidence for entity canonical names and aliases.

Revision ID: v24_entity_name_evidence
Revises: v23_l0_tactic_source_tombstones
"""

from __future__ import annotations

from alembic import op

revision = "v24_entity_name_evidence"
down_revision = "v23_l0_tactic_source_tombstones"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE entity_catalog
    ADD COLUMN canonical_name_is_independent INTEGER NOT NULL DEFAULT 0
    CHECK(canonical_name_is_independent IN (0, 1));
ALTER TABLE entity_aliases
    ADD COLUMN is_independent INTEGER NOT NULL DEFAULT 0
    CHECK(is_independent IN (0, 1));

CREATE TABLE entity_name_evidence (
    entity_id TEXT NOT NULL,
    name_kind TEXT NOT NULL CHECK(name_kind IN ('canonical', 'alias')),
    normalized_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    event_id TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(entity_id, name_kind, normalized_name, event_id),
    FOREIGN KEY(entity_id) REFERENCES entity_catalog(entity_id) ON DELETE CASCADE
);
CREATE INDEX idx_entity_name_evidence_event
    ON entity_name_evidence(event_id, entity_id, name_kind);
CREATE INDEX idx_entity_name_evidence_name
    ON entity_name_evidence(entity_id, name_kind, normalized_name, confidence DESC);

INSERT OR IGNORE INTO entity_name_evidence(
    entity_id, name_kind, normalized_name, display_name,
    event_id, confidence, created_at, updated_at
)
SELECT catalog.entity_id,
       'canonical',
       LOWER(TRIM(catalog.canonical_name)),
       catalog.canonical_name,
       TRIM(CAST(evidence.value AS TEXT)),
       COALESCE(mention.confidence, 0.5),
       MIN(catalog.created_at, mention.created_at),
       MAX(catalog.updated_at, mention.created_at)
FROM entity_catalog AS catalog
JOIN entity_mentions AS mention
  ON mention.resolved_entity_id = catalog.entity_id
JOIN json_each(CASE
    WHEN json_valid(mention.evidence_event_ids)
         AND json_type(mention.evidence_event_ids) = 'array'
        THEN mention.evidence_event_ids
    ELSE '[]'
END) AS evidence
WHERE evidence.type = 'text'
  AND TRIM(CAST(evidence.value AS TEXT)) != ''
  AND (
      LOWER(TRIM(catalog.canonical_name)) = LOWER(TRIM(mention.mention_text))
      OR LOWER(TRIM(catalog.canonical_name)) = LOWER(TRIM(mention.normalized_surface))
      OR TRIM(catalog.canonical_name) = TRIM(mention.mention_text)
      OR TRIM(catalog.canonical_name) = TRIM(mention.normalized_surface)
  )
  AND NOT EXISTS (
      SELECT 1 FROM memory_source_event_tombstones AS tombstone
      WHERE tombstone.event_id = TRIM(CAST(evidence.value AS TEXT))
  );

INSERT OR IGNORE INTO entity_name_evidence(
    entity_id, name_kind, normalized_name, display_name,
    event_id, confidence, created_at, updated_at
)
SELECT alias.entity_id,
       'alias',
       alias.normalized_alias,
       alias.alias_text,
       TRIM(CAST(evidence.value AS TEXT)),
       MAX(alias.confidence, COALESCE(mention.confidence, 0.5)),
       MIN(alias.created_at, mention.created_at),
       MAX(alias.updated_at, mention.created_at)
FROM entity_aliases AS alias
JOIN entity_mentions AS mention
  ON mention.resolved_entity_id = alias.entity_id
JOIN json_each(CASE
    WHEN json_valid(mention.evidence_event_ids)
         AND json_type(mention.evidence_event_ids) = 'array'
        THEN mention.evidence_event_ids
    ELSE '[]'
END) AS evidence
WHERE evidence.type = 'text'
  AND TRIM(CAST(evidence.value AS TEXT)) != ''
  AND (
      alias.normalized_alias = LOWER(TRIM(mention.mention_text))
      OR alias.normalized_alias = LOWER(TRIM(mention.normalized_surface))
      OR TRIM(alias.alias_text) = TRIM(mention.mention_text)
      OR TRIM(alias.alias_text) = TRIM(mention.normalized_surface)
  )
  AND NOT EXISTS (
      SELECT 1 FROM memory_source_event_tombstones AS tombstone
      WHERE tombstone.event_id = TRIM(CAST(evidence.value AS TEXT))
  );

UPDATE entity_catalog
SET canonical_name_is_independent = 0
WHERE EXISTS (
    SELECT 1 FROM entity_name_evidence AS evidence
    WHERE evidence.entity_id = entity_catalog.entity_id
      AND evidence.name_kind = 'canonical'
      AND evidence.normalized_name = LOWER(TRIM(entity_catalog.canonical_name))
);

UPDATE entity_aliases
SET is_independent = 0
WHERE EXISTS (
    SELECT 1 FROM entity_name_evidence AS evidence
    WHERE evidence.entity_id = entity_aliases.entity_id
      AND evidence.name_kind = 'alias'
      AND evidence.normalized_name = entity_aliases.normalized_alias
);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_entity_name_evidence_name;
DROP INDEX IF EXISTS idx_entity_name_evidence_event;
DROP TABLE entity_name_evidence;
ALTER TABLE entity_aliases DROP COLUMN is_independent;
ALTER TABLE entity_catalog DROP COLUMN canonical_name_is_independent;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v24_entity_name_evidence")
    try:
        for statement in _statements(SCHEMA_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v24_entity_name_evidence")
        connection.execute("RELEASE SAVEPOINT v24_entity_name_evidence")
        raise
    connection.execute("RELEASE SAVEPOINT v24_entity_name_evidence")


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute("SELECT COUNT(*) FROM entity_name_evidence").fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError("Cannot downgrade entity name evidence while retained data exists")
    connection.execute("SAVEPOINT v24_entity_name_evidence_down")
    try:
        for statement in _statements(DROP_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v24_entity_name_evidence_down")
        connection.execute("RELEASE SAVEPOINT v24_entity_name_evidence_down")
        raise
    connection.execute("RELEASE SAVEPOINT v24_entity_name_evidence_down")


def _statements(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
