"""Replace task-shaped L0 projections with session attention state."""

from __future__ import annotations

from alembic import op

revision = "v35_l0_attention_state"
down_revision = "v34_remove_l0_execution_state"
branch_labels = None
depends_on = None


CREATE_STATEMENTS = (
    """
CREATE TABLE IF NOT EXISTS l0_attention_items (
    item_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL,
    salience REAL NOT NULL,
    confidence REAL NOT NULL,
    evidence_mode TEXT NOT NULL,
    source_turn_ids TEXT NOT NULL DEFAULT '[]',
    source_event_ids TEXT NOT NULL DEFAULT '[]',
    entity_id TEXT,
    task_id TEXT,
    task_attempt INTEGER,
    first_seen_at REAL NOT NULL,
    last_reinforced_at REAL NOT NULL,
    expires_at REAL,
    supersedes_item_id TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l0_attention_session_status
    ON l0_attention_items(session_id, status, salience DESC, last_reinforced_at DESC)
""",
    """
CREATE TABLE IF NOT EXISTS l0_forgotten_attention_source_refs (
    source_ref TEXT PRIMARY KEY,
    created_at REAL NOT NULL
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l0_forgotten_attention_source_refs_created
    ON l0_forgotten_attention_source_refs(created_at, source_ref)
    """,
    """
CREATE TABLE IF NOT EXISTS memory_source_turn_cutoffs (
    turn_id TEXT PRIMARY KEY,
    cutoff_at REAL NOT NULL,
    reason TEXT NOT NULL,
    updated_at REAL NOT NULL
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_memory_source_turn_cutoffs_cutoff
    ON memory_source_turn_cutoffs(cutoff_at, turn_id)
    """,
    """
CREATE TABLE IF NOT EXISTS l0_forgotten_attention_entities (
    entity_id TEXT PRIMARY KEY,
    cutoff_at REAL NOT NULL,
    operation_id TEXT,
    updated_at REAL NOT NULL
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l0_forgotten_attention_entities_cutoff
    ON l0_forgotten_attention_entities(cutoff_at, entity_id)
    """,
)
MIGRATE_LEGACY_STATEMENTS = (
    """
INSERT OR IGNORE INTO l0_forgotten_attention_source_refs(source_ref, created_at)
SELECT source_ref, created_at
FROM l0_forgotten_tactic_source_refs
""",
)
DROP_LEGACY_STATEMENTS = (
    "DROP TABLE IF EXISTS l0_goal_stack",
    "DROP TABLE IF EXISTS l0_active_entities",
    "DROP TABLE IF EXISTS l0_temporary_tactics",
    "DROP TABLE IF EXISTS l0_forgotten_tactic_source_refs",
)
CREATE_SQL = ";\n".join(
    statement.strip() for statement in CREATE_STATEMENTS
) + ";"
MIGRATE_LEGACY_SQL = ";\n".join(
    statement.strip() for statement in MIGRATE_LEGACY_STATEMENTS
) + ";"
DROP_LEGACY_SQL = ";\n".join(DROP_LEGACY_STATEMENTS) + ";"


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a fresh shared-memory database."""

    return f"{CREATE_SQL}\n{MIGRATE_LEGACY_SQL}\n{DROP_LEGACY_SQL}"


def upgrade() -> None:
    for statement in CREATE_STATEMENTS:
        op.execute(statement.strip())
    for statement in MIGRATE_LEGACY_STATEMENTS:
        op.execute(statement.strip())
    for statement in DROP_LEGACY_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Legacy L0 task projections cannot be restored")


__all__ = [
    "CREATE_SQL",
    "CREATE_STATEMENTS",
    "DROP_LEGACY_SQL",
    "DROP_LEGACY_STATEMENTS",
    "MIGRATE_LEGACY_SQL",
    "MIGRATE_LEGACY_STATEMENTS",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
