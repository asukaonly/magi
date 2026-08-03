"""Separate L2-projected entity links from durable manual L1 links."""

from __future__ import annotations

from alembic import op

revision = "v2_l2_entity_link_projections"
down_revision = "v1"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l1_entity_link_projection_generation (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    clear_generation INTEGER NOT NULL CHECK (clear_generation >= 0),
    updated_at REAL NOT NULL
);

INSERT OR IGNORE INTO l1_entity_link_projection_generation(
    singleton_id, clear_generation, updated_at
) VALUES (1, 0, 0.0);

CREATE TABLE IF NOT EXISTS l1_event_entity_projection_state (
    event_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision > 0),
    lease_token TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
    payload_fingerprint TEXT NOT NULL CHECK (TRIM(payload_fingerprint) != ''),
    applied_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS l1_projected_event_entities (
    event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT,
    confidence REAL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    lease_token TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
    created_at REAL NOT NULL,
    PRIMARY KEY(event_id, entity_id),
    FOREIGN KEY(event_id) REFERENCES l1_event_entity_projection_state(event_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_l1_projected_event_entities_entity
    ON l1_projected_event_entities(entity_id);

CREATE VIEW IF NOT EXISTS l1_effective_event_entities AS
SELECT
    event_id,
    entity_id,
    MAX(entity_type) AS entity_type,
    MAX(confidence) AS confidence,
    MAX(created_at) AS created_at
FROM (
    SELECT event_id, entity_id, entity_type, confidence, created_at
    FROM l1_event_entities
    UNION ALL
    SELECT event_id, entity_id, entity_type, confidence, created_at
    FROM l1_projected_event_entities
)
GROUP BY event_id, entity_id;
"""


def upgrade() -> None:
    # Before this revision the only production writer was L2 and rows carried
    # no ownership metadata. Clear the rebuildable projection instead of
    # misclassifying stale derived data as permanent manual truth.
    op.execute("DELETE FROM l1_event_entities")
    op.get_bind().connection.executescript(SCHEMA_SQL)


def schema_sql_for_fresh_database() -> str:
    """Return the release schema addition for a fresh L1 database."""

    return SCHEMA_SQL


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS l1_effective_event_entities")
    op.execute("DROP INDEX IF EXISTS idx_l1_projected_event_entities_entity")
    op.execute("DROP TABLE IF EXISTS l1_projected_event_entities")
    op.execute("DROP TABLE IF EXISTS l1_event_entity_projection_state")
    op.execute("DROP TABLE IF EXISTS l1_entity_link_projection_generation")


__all__ = ["SCHEMA_SQL", "downgrade", "schema_sql_for_fresh_database", "upgrade"]
