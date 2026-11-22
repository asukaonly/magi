"""Allow source_records selector kind in durable forget operations.

Revision ID: v61_source_records_forget_selector
Revises: v60_vector_projection_journal
"""

from __future__ import annotations

from alembic import op

revision = "v61_source_records_forget_selector"
down_revision = "v60_vector_projection_journal"
branch_labels = None
depends_on = None


_COLUMNS = (
    "operation_id, selector_kind, selector_hash, selector_json, reason, status, phase, "
    "projection_cursor, projection_selection_complete, cursor, selection_complete, "
    "selector_cleanup_complete, total_event_count, active_event_count, cleaned_event_count, "
    "attempt_count, lease_owner, lease_token, lease_expires_at, last_error, result_json, "
    "created_at, updated_at, completed_at, surface_finalized_at, execution_ready"
)


def _create_table_sql(table_name: str, selector_kinds_sql: str) -> str:
    return f"""
CREATE TABLE {table_name} (
    operation_id TEXT PRIMARY KEY,
    selector_kind TEXT NOT NULL CHECK(selector_kind IN (
        {selector_kinds_sql}
    )),
    selector_hash TEXT NOT NULL,
    selector_json TEXT NOT NULL CHECK(json_valid(selector_json)),
    reason TEXT NOT NULL CHECK(TRIM(reason) != ''),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN (
        'pending', 'running', 'failed', 'completed'
    )),
    phase TEXT NOT NULL DEFAULT 'barrier' CHECK(phase IN (
        'barrier', 'target_cleanup', 'source_cleanup', 'completed'
    )),
    projection_cursor TEXT NOT NULL DEFAULT '',
    projection_selection_complete INTEGER NOT NULL DEFAULT 0
        CHECK(projection_selection_complete IN (0, 1)),
    cursor TEXT NOT NULL DEFAULT '',
    selection_complete INTEGER NOT NULL DEFAULT 0 CHECK(selection_complete IN (0, 1)),
    selector_cleanup_complete INTEGER NOT NULL DEFAULT 0
        CHECK(selector_cleanup_complete IN (0, 1)),
    total_event_count INTEGER NOT NULL DEFAULT 0 CHECK(total_event_count >= 0),
    active_event_count INTEGER NOT NULL DEFAULT 0 CHECK(active_event_count >= 0),
    cleaned_event_count INTEGER NOT NULL DEFAULT 0 CHECK(cleaned_event_count >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    lease_owner TEXT,
    lease_token INTEGER NOT NULL DEFAULT 0 CHECK(lease_token >= 0),
    lease_expires_at REAL,
    last_error TEXT,
    result_json TEXT NOT NULL DEFAULT '{{}}' CHECK(json_valid(result_json)),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    surface_finalized_at REAL,
    execution_ready INTEGER NOT NULL DEFAULT 1
        CHECK(execution_ready IN (0, 1))
);
"""


_INDEXES_SQL = """
CREATE UNIQUE INDEX idx_memory_forget_operations_active_selector
    ON memory_forget_operations(selector_kind, selector_hash)
    WHERE status != 'completed';
CREATE INDEX idx_memory_forget_operations_recovery
    ON memory_forget_operations(status, lease_expires_at, updated_at, operation_id)
    WHERE status != 'completed';
CREATE INDEX idx_memory_forget_operations_selector_history
    ON memory_forget_operations(selector_kind, selector_hash, created_at DESC);
CREATE INDEX idx_memory_forget_operations_surface_recovery
    ON memory_forget_operations(completed_at, operation_id)
    WHERE status = 'completed'
      AND surface_finalized_at IS NULL
      AND selector_kind IN ('chat_session', 'chat_history', 'chat_message');
CREATE INDEX IF NOT EXISTS idx_memory_forget_operations_activation
    ON memory_forget_operations(
        execution_ready, status, lease_expires_at, updated_at, operation_id
    )
    WHERE status != 'completed';
"""


_V61_SELECTOR_KINDS = (
    "'known_events', 'entity', 'time_range', 'episode', 'source_records', "
    "'chat_session', 'chat_history', 'chat_message'"
)
_V60_SELECTOR_KINDS = (
    "'known_events', 'entity', 'time_range', 'episode', "
    "'chat_session', 'chat_history', 'chat_message'"
)

SCHEMA_SQL = f"""
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_memory_forget_operations_activation;
DROP INDEX IF EXISTS idx_memory_forget_operations_surface_recovery;
DROP INDEX IF EXISTS idx_memory_forget_operations_selector_history;
DROP INDEX IF EXISTS idx_memory_forget_operations_recovery;
DROP INDEX IF EXISTS idx_memory_forget_operations_active_selector;
{_create_table_sql("memory_forget_operations_v61", _V61_SELECTOR_KINDS)}
INSERT INTO memory_forget_operations_v61({_COLUMNS})
SELECT {_COLUMNS} FROM memory_forget_operations;
DROP TABLE memory_forget_operations;
ALTER TABLE memory_forget_operations_v61 RENAME TO memory_forget_operations;
{_INDEXES_SQL}
"""

DROP_SQL = f"""
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_memory_forget_operations_activation;
DROP INDEX IF EXISTS idx_memory_forget_operations_surface_recovery;
DROP INDEX IF EXISTS idx_memory_forget_operations_selector_history;
DROP INDEX IF EXISTS idx_memory_forget_operations_recovery;
DROP INDEX IF EXISTS idx_memory_forget_operations_active_selector;
{_create_table_sql("memory_forget_operations_v60", _V60_SELECTOR_KINDS)}
INSERT INTO memory_forget_operations_v60({_COLUMNS})
SELECT {_COLUMNS} FROM memory_forget_operations
WHERE selector_kind != 'source_records';
DROP TABLE memory_forget_operations;
ALTER TABLE memory_forget_operations_v60 RENAME TO memory_forget_operations;
{_INDEXES_SQL}
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a new shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    fk_row = connection.execute("PRAGMA foreign_keys").fetchone()
    fk_enabled = bool(fk_row and fk_row[0])
    connection.executescript(SCHEMA_SQL)
    if fk_enabled:
        connection.execute("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    connection = op.get_bind().connection
    fk_row = connection.execute("PRAGMA foreign_keys").fetchone()
    fk_enabled = bool(fk_row and fk_row[0])
    connection.executescript(DROP_SQL)
    if fk_enabled:
        connection.execute("PRAGMA foreign_keys = ON")


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
