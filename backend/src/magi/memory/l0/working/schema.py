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

CREATE TABLE IF NOT EXISTS l0_goal_stack (
    stack_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    parent_goal_id TEXT,
    goal_type TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    result_summary TEXT,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS l0_active_entities (
    session_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    relevance_score REAL DEFAULT 0.0,
    snapshot_json TEXT NOT NULL,
    source_event_ids TEXT NOT NULL DEFAULT '[]',
    loaded_at REAL NOT NULL,
    last_accessed_at REAL NOT NULL,
    access_count INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, entity_id, entity_type)
);

CREATE TABLE IF NOT EXISTS l0_temporary_tactics (
    tactic_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    tactic_type TEXT NOT NULL,
    tactic_payload TEXT NOT NULL,
    source_event_ids TEXT NOT NULL,
    expires_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS l0_forgotten_tactic_source_refs (
    source_ref TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_l0_forgotten_tactic_source_refs_created
    ON l0_forgotten_tactic_source_refs(created_at, source_ref);

CREATE TABLE IF NOT EXISTS l0_execution_runs (
    session_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    root_turn_id TEXT,
    root_user_message TEXT NOT NULL,
    response_anchor_turn_id TEXT,
    cancel_requested_at REAL,
    cancel_reason TEXT,
    cancel_requested_by TEXT,
    cancel_anchor_turn_id TEXT,
    trigger_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS l0_execution_pending_turns (
    pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    content TEXT NOT NULL,
    revision INTEGER NOT NULL,
    disposition TEXT NOT NULL DEFAULT 'augment',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS l0_execution_results (
    result_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

L0_CLEAR_SQL = """
DELETE FROM l0_sessions;
DELETE FROM l0_goal_stack;
DELETE FROM l0_active_entities;
DELETE FROM l0_temporary_tactics;
DELETE FROM l0_forgotten_tactic_source_refs;
DELETE FROM l0_execution_runs;
DELETE FROM l0_execution_pending_turns;
DELETE FROM l0_execution_results;
"""


async def ensure_l0_checkpoint_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(L0_SCHEMA_SQL)


async def clear_l0_checkpoint_tables(db: aiosqlite.Connection) -> None:
    await db.executescript(L0_CLEAR_SQL)
