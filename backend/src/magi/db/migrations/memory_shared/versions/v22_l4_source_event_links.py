"""Add durable source-event lineage for L4 procedural skills.

Revision ID: v22_l4_source_event_links
Revises: v21_source_event_forgetting
"""

from __future__ import annotations

from alembic import op

revision = "v22_l4_source_event_links"
down_revision = "v21_source_event_forgetting"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE l4_skill_event_links (
    skill_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(skill_id, event_id),
    FOREIGN KEY(skill_id) REFERENCES procedural_skills(skill_id) ON DELETE CASCADE
);
CREATE INDEX idx_l4_skill_event_links_event
    ON l4_skill_event_links(event_id, skill_id);

INSERT OR IGNORE INTO l4_skill_event_links(skill_id, event_id, created_at)
SELECT skills.skill_id, TRIM(CAST(source.value AS TEXT)), skills.updated_at
FROM procedural_skills AS skills
JOIN json_each(
    CASE
        WHEN json_valid(skills.source_event_ids) THEN skills.source_event_ids
        ELSE '[]'
    END
) AS source
WHERE source.type = 'text' AND TRIM(CAST(source.value AS TEXT)) != '';

INSERT OR IGNORE INTO l4_skill_event_links(skill_id, event_id, created_at)
SELECT traces.skill_id, TRIM(traces.event_id), traces.created_at
FROM l4_execution_traces AS traces
JOIN procedural_skills AS skills ON skills.skill_id = traces.skill_id
WHERE TRIM(traces.event_id) != '';

-- Pre-governance rows kept only bounded source and trace lists. If the durable
-- attempt count exceeds the recovered links, some source is unknowable and the
-- aggregate cannot satisfy a future delete request. Retire only those rows;
-- fully attributable legacy rows remain usable.
DELETE FROM l4_skills_fts
WHERE skill_id IN (
    SELECT skills.skill_id
    FROM procedural_skills AS skills
    WHERE skills.deleted_at IS NULL
      AND skills.total_attempts > (
          SELECT COUNT(*) FROM l4_skill_event_links AS links
          WHERE links.skill_id = skills.skill_id
      )
);
DELETE FROM l4_skill_chunks
WHERE skill_id IN (
    SELECT skills.skill_id
    FROM procedural_skills AS skills
    WHERE skills.deleted_at IS NULL
      AND skills.total_attempts > (
          SELECT COUNT(*) FROM l4_skill_event_links AS links
          WHERE links.skill_id = skills.skill_id
      )
);
DELETE FROM l4_execution_traces
WHERE skill_id IN (
    SELECT skills.skill_id
    FROM procedural_skills AS skills
    WHERE skills.deleted_at IS NULL
      AND skills.total_attempts > (
          SELECT COUNT(*) FROM l4_skill_event_links AS links
          WHERE links.skill_id = skills.skill_id
      )
);

UPDATE procedural_skills
SET skill_name = '__legacy_unattributed__:' || skill_id,
    skill_category = '__legacy_unattributed__',
    skill_type = '__legacy_unattributed__',
    proficiency = 0.0,
    total_attempts = 0,
    success_count = 0,
    failure_count = 0,
    success_rate = 0.0,
    avg_execution_time_ms = NULL,
    min_execution_time_ms = NULL,
    max_execution_time_ms = NULL,
    p95_execution_time_ms = NULL,
    circuit_breaker_state = 'closed',
    circuit_breaker_opened_at = NULL,
    circuit_breaker_failure_count = 0,
    circuit_breaker_success_count = 0,
    optimized_prompt = NULL,
    optimized_params = '{}',
    optimization_score = NULL,
    context_affinity = '{}',
    source_event_ids = '[]',
    last_used_at = NULL,
    last_success_at = NULL,
    last_failure_at = NULL,
    embedding_status = 'disabled',
    embedding_profile_id = NULL,
    embedding_chunk_count = 0,
    last_embedded_at = NULL,
    pending_trace_count = 0,
    deleted_at = COALESCE(deleted_at, updated_at)
WHERE deleted_at IS NULL
  AND total_attempts > (
      SELECT COUNT(*) FROM l4_skill_event_links AS links
      WHERE links.skill_id = procedural_skills.skill_id
  );
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_l4_skill_event_links_event;
DROP TABLE IF EXISTS l4_skill_event_links;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v22_l4_source_event_links")
    try:
        for statement in _statements(SCHEMA_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v22_l4_source_event_links")
        connection.execute("RELEASE SAVEPOINT v22_l4_source_event_links")
        raise
    connection.execute("RELEASE SAVEPOINT v22_l4_source_event_links")


def downgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v22_l4_source_event_links_down")
    try:
        retained = connection.execute("SELECT COUNT(*) FROM l4_skill_event_links").fetchone()
        if retained is not None and int(retained[0]) > 0:
            raise RuntimeError("Cannot downgrade L4 source-event links while retained data exists")
        for statement in _statements(DROP_SQL):
            connection.execute(statement)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v22_l4_source_event_links_down")
        connection.execute("RELEASE SAVEPOINT v22_l4_source_event_links_down")
        raise
    connection.execute("RELEASE SAVEPOINT v22_l4_source_event_links_down")


def _statements(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
