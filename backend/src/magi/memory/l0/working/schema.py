"""SQLite schema helpers for L0 working-memory checkpoints.

Schema is owned by alembic (``magi.db.migrations.memory_shared``).
"""

from __future__ import annotations

import aiosqlite

L0_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l0_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT,
    runtime_agent_id TEXT,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    last_active_at REAL NOT NULL,
    last_checkpoint_at REAL,
    metadata TEXT
);

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
);

CREATE INDEX IF NOT EXISTS idx_l0_attention_session_status
    ON l0_attention_items(session_id, status, salience DESC, last_reinforced_at DESC);

CREATE TABLE IF NOT EXISTS l0_forgotten_attention_source_refs (
    source_ref TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_l0_forgotten_attention_source_refs_created
    ON l0_forgotten_attention_source_refs(created_at, source_ref);

CREATE TABLE IF NOT EXISTS memory_source_turn_cutoffs (
    turn_id TEXT PRIMARY KEY,
    cutoff_at REAL NOT NULL,
    reason TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_source_turn_cutoffs_cutoff
    ON memory_source_turn_cutoffs(cutoff_at, turn_id);

CREATE TABLE IF NOT EXISTS l0_forgotten_attention_entities (
    entity_id TEXT PRIMARY KEY,
    cutoff_at REAL NOT NULL,
    operation_id TEXT,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_l0_forgotten_attention_entities_cutoff
    ON l0_forgotten_attention_entities(cutoff_at, entity_id);

"""

L0_CLEAR_SQL = """
DELETE FROM l0_sessions;
DELETE FROM l0_attention_items;
DELETE FROM l0_forgotten_attention_source_refs;
DELETE FROM l0_forgotten_attention_entities;
"""


async def ensure_l0_checkpoint_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(L0_SCHEMA_SQL)


async def clear_l0_checkpoint_tables(db: aiosqlite.Connection) -> None:
    await db.executescript(L0_CLEAR_SQL)
