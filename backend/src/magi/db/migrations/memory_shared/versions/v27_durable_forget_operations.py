"""Persist resumable cross-layer forget operations.

Revision ID: v27_durable_forget_operations
Revises: v26_manual_entry_projection_intent
"""

from __future__ import annotations

import sqlite3

from alembic import op

revision = "v27_durable_forget_operations"
down_revision = "v26_manual_entry_projection_intent"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE l0_active_entities
    ADD COLUMN source_event_ids TEXT NOT NULL DEFAULT '[]';

CREATE TABLE memory_forget_operations (
    operation_id TEXT PRIMARY KEY,
    selector_kind TEXT NOT NULL CHECK(selector_kind IN (
        'known_events', 'entity', 'time_range', 'episode',
        'chat_session', 'chat_history', 'chat_message'
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
    result_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(result_json)),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    surface_finalized_at REAL
);
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

CREATE TABLE memory_forget_operation_events (
    operation_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    was_active INTEGER NOT NULL CHECK(was_active IN (0, 1)),
    cleanup_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(cleanup_status IN ('pending', 'completed')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(operation_id, event_id),
    FOREIGN KEY(operation_id) REFERENCES memory_forget_operations(operation_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_memory_forget_operation_events_pending
    ON memory_forget_operation_events(operation_id, cleanup_status, event_id)
    WHERE cleanup_status = 'pending';

CREATE TABLE memory_forget_operation_refs (
    operation_id TEXT NOT NULL,
    item_event_id TEXT NOT NULL DEFAULT '',
    ref_role TEXT NOT NULL CHECK(ref_role IN ('barrier', 'cleanup', 'target')),
    ref_type TEXT NOT NULL CHECK(ref_type IN (
        'exact_event', 'audit_event', 'turn', 'chat_session',
        'source_item', 'idempotency', 'chat_projection'
        , 'entity_refresh', 'entity_refresh_prepared'
    )),
    source_ref TEXT NOT NULL CHECK(TRIM(source_ref) != ''),
    created_at REAL NOT NULL,
    PRIMARY KEY(operation_id, item_event_id, ref_role, ref_type, source_ref),
    FOREIGN KEY(operation_id) REFERENCES memory_forget_operations(operation_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_memory_forget_operation_refs_item
    ON memory_forget_operation_refs(
        operation_id, item_event_id, ref_role, ref_type, source_ref
    );

CREATE TABLE memory_projection_blocks (
    block_kind TEXT NOT NULL CHECK(block_kind IN (
        'episode_formation', 'entity_projection',
        'entity_projection_candidate'
    )),
    target_id TEXT NOT NULL CHECK(TRIM(target_id) != ''),
    event_id TEXT NOT NULL CHECK(TRIM(event_id) != ''),
    operation_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(block_kind, target_id, event_id),
    FOREIGN KEY(operation_id) REFERENCES memory_forget_operations(operation_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_memory_projection_blocks_event
    ON memory_projection_blocks(block_kind, event_id, target_id);
CREATE INDEX idx_memory_projection_blocks_operation
    ON memory_projection_blocks(operation_id, block_kind, event_id);

CREATE TABLE memory_entity_projection_identity_blocks (
    target_id TEXT NOT NULL CHECK(TRIM(target_id) != ''),
    event_id TEXT NOT NULL CHECK(TRIM(event_id) != ''),
    normalized_surface TEXT NOT NULL CHECK(TRIM(normalized_surface) != ''),
    entity_type TEXT NOT NULL DEFAULT '',
    operation_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(target_id, event_id, normalized_surface, entity_type),
    FOREIGN KEY(operation_id) REFERENCES memory_forget_operations(operation_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_memory_entity_projection_identity_lookup
    ON memory_entity_projection_identity_blocks(
        event_id, normalized_surface, entity_type, target_id
    );

CREATE TRIGGER block_forgotten_episode_event_projection
BEFORE INSERT ON episode_events
WHEN EXISTS (
    SELECT 1
    FROM memory_projection_blocks AS block
    WHERE block.event_id = NEW.event_id
      AND (
          block.block_kind = 'episode_formation'
          OR (
              block.block_kind IN (
                  'entity_projection', 'entity_projection_candidate'
              )
              AND block.target_id IN (
                  SELECT CAST(entity.value AS TEXT)
                  FROM json_each(
                      COALESCE(
                          (SELECT primary_entity_ids FROM episodes
                           WHERE episode_id = NEW.episode_id),
                          '[]'
                      )
                  ) AS entity
              )
          )
      )
)
BEGIN
    SELECT RAISE(IGNORE);
END;
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_memory_forget_operation_refs_item;
DROP TABLE IF EXISTS memory_forget_operation_refs;
DROP INDEX IF EXISTS idx_memory_projection_blocks_operation;
DROP INDEX IF EXISTS idx_memory_projection_blocks_event;
DROP TRIGGER IF EXISTS block_forgotten_episode_event_projection;
DROP INDEX IF EXISTS idx_memory_entity_projection_identity_lookup;
DROP TABLE IF EXISTS memory_entity_projection_identity_blocks;
DROP TABLE IF EXISTS memory_projection_blocks;
DROP INDEX IF EXISTS idx_memory_forget_operation_events_pending;
DROP TABLE IF EXISTS memory_forget_operation_events;
DROP INDEX IF EXISTS idx_memory_forget_operations_surface_recovery;
DROP INDEX IF EXISTS idx_memory_forget_operations_selector_history;
DROP INDEX IF EXISTS idx_memory_forget_operations_recovery;
DROP INDEX IF EXISTS idx_memory_forget_operations_active_selector;
DROP TABLE IF EXISTS memory_forget_operations;
ALTER TABLE l0_active_entities DROP COLUMN source_event_ids;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a new shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    _execute_script_atomically(
        op.get_bind().connection,
        SCHEMA_SQL,
        savepoint="v27_durable_forget_operations",
    )


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute("SELECT COUNT(*) FROM memory_forget_operations").fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError("Cannot downgrade durable forget operations while history exists")
    _execute_script_atomically(
        connection,
        DROP_SQL,
        savepoint="v27_durable_forget_operations_down",
    )


def _execute_script_atomically(connection, script: str, *, savepoint: str) -> None:
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        for statement in _statements(script):
            connection.execute(statement)
    except Exception:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def _statements(script: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                statements.append(statement)
            pending = ""
    if pending.strip():
        raise ValueError("Incomplete SQLite migration statement")
    return statements


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
