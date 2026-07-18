"""Persist source-owner obligations in durable forget operations.

Revision ID: v32_forget_source_owner_refs
Revises: v31_correction_replacement_slot_index
"""

from __future__ import annotations

from alembic import op

revision = "v32_forget_source_owner_refs"
down_revision = "v31_correction_replacement_slot_index"
branch_labels = None
depends_on = None


_CREATE_REFS_TABLE = """
CREATE TABLE memory_forget_operation_refs_v32 (
    operation_id TEXT NOT NULL,
    item_event_id TEXT NOT NULL DEFAULT '',
    ref_role TEXT NOT NULL CHECK(ref_role IN ('barrier', 'cleanup', 'target')),
    ref_type TEXT NOT NULL CHECK(ref_type IN (
        'exact_event', 'audit_event', 'turn', 'chat_session',
        'source_item', 'idempotency', 'chat_projection',
        'entity_refresh', 'entity_refresh_prepared', 'source_owner'
    )),
    source_ref TEXT NOT NULL CHECK(TRIM(source_ref) != ''),
    created_at REAL NOT NULL,
    PRIMARY KEY(operation_id, item_event_id, ref_role, ref_type, source_ref),
    FOREIGN KEY(operation_id) REFERENCES memory_forget_operations(operation_id)
        ON DELETE CASCADE
);
"""

SCHEMA_SQL = f"""
DROP INDEX IF EXISTS idx_memory_forget_operation_refs_item;
{_CREATE_REFS_TABLE}
INSERT INTO memory_forget_operation_refs_v32(
    operation_id, item_event_id, ref_role, ref_type, source_ref, created_at
)
SELECT operation_id, item_event_id, ref_role, ref_type, source_ref, created_at
FROM memory_forget_operation_refs;
DROP TABLE memory_forget_operation_refs;
ALTER TABLE memory_forget_operation_refs_v32
    RENAME TO memory_forget_operation_refs;
CREATE INDEX idx_memory_forget_operation_refs_item
    ON memory_forget_operation_refs(
        operation_id, item_event_id, ref_role, ref_type, source_ref
    );
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_memory_forget_operation_refs_item;
CREATE TABLE memory_forget_operation_refs_v31 (
    operation_id TEXT NOT NULL,
    item_event_id TEXT NOT NULL DEFAULT '',
    ref_role TEXT NOT NULL CHECK(ref_role IN ('barrier', 'cleanup', 'target')),
    ref_type TEXT NOT NULL CHECK(ref_type IN (
        'exact_event', 'audit_event', 'turn', 'chat_session',
        'source_item', 'idempotency', 'chat_projection',
        'entity_refresh', 'entity_refresh_prepared'
    )),
    source_ref TEXT NOT NULL CHECK(TRIM(source_ref) != ''),
    created_at REAL NOT NULL,
    PRIMARY KEY(operation_id, item_event_id, ref_role, ref_type, source_ref),
    FOREIGN KEY(operation_id) REFERENCES memory_forget_operations(operation_id)
        ON DELETE CASCADE
);
INSERT INTO memory_forget_operation_refs_v31(
    operation_id, item_event_id, ref_role, ref_type, source_ref, created_at
)
SELECT operation_id, item_event_id, ref_role, ref_type, source_ref, created_at
FROM memory_forget_operation_refs
WHERE ref_type != 'source_owner';
DROP TABLE memory_forget_operation_refs;
ALTER TABLE memory_forget_operation_refs_v31
    RENAME TO memory_forget_operation_refs;
CREATE INDEX idx_memory_forget_operation_refs_item
    ON memory_forget_operation_refs(
        operation_id, item_event_id, ref_role, ref_type, source_ref
    );
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a new shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
