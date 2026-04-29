"""SQLite schema constants for L4 procedural memory."""
from __future__ import annotations

import aiosqlite

SKILL_CHUNKS_TABLE = "l4_skill_chunks"
EXECUTION_TRACES_TABLE = "l4_execution_traces"
EMBEDDING_TEXT_BUILDER_VERSION = "l4_skill_v1"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_DISABLED = "disabled"

MAX_TRACES_PER_SKILL = 50
DEFAULT_STRATEGY_EXTRACTION_THRESHOLD = 5
_ADAPTIVE_MAX_THRESHOLD = 100

PROCEDURAL_MEMORY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS procedural_skills (
    skill_id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    skill_category TEXT NOT NULL,
    skill_type TEXT NOT NULL,
    proficiency REAL NOT NULL DEFAULT 0.0,
    total_attempts INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    success_rate REAL NOT NULL DEFAULT 0.0,
    avg_execution_time_ms REAL,
    min_execution_time_ms REAL,
    max_execution_time_ms REAL,
    p95_execution_time_ms REAL,
    circuit_breaker_state TEXT NOT NULL DEFAULT 'closed',
    circuit_breaker_opened_at REAL,
    circuit_breaker_failure_count INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_success_count INTEGER NOT NULL DEFAULT 0,
    optimized_prompt TEXT,
    optimized_params TEXT,
    optimization_score REAL,
    context_affinity TEXT,
    source_event_ids TEXT NOT NULL,
    last_used_at REAL,
    last_success_at REAL,
    last_failure_at REAL,
    embedding_status TEXT NOT NULL DEFAULT 'disabled',
    embedding_profile_id TEXT,
    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
    last_embedded_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(skill_name, skill_category)
);
CREATE INDEX IF NOT EXISTS idx_procedural_skill_name ON procedural_skills(skill_name, skill_category);

CREATE TABLE IF NOT EXISTS l4_skill_chunks (
    chunk_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    token_estimate INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l4_skill_chunks_skill ON l4_skill_chunks(skill_id);
CREATE INDEX IF NOT EXISTS idx_l4_skill_chunks_index ON l4_skill_chunks(skill_id, chunk_index);

CREATE VIRTUAL TABLE IF NOT EXISTS l4_skills_fts USING fts5(
    skill_id UNINDEXED,
    content,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS l4_execution_traces (
    trace_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    turn_id TEXT,
    success INTEGER NOT NULL,
    duration_ms REAL,
    error_summary TEXT,
    input_summary TEXT,
    output_summary TEXT,
    task_context TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l4_traces_skill
    ON l4_execution_traces(skill_id, created_at DESC);
"""

PENDING_TRACE_COUNT_MIGRATION_SQL = (
    "ALTER TABLE procedural_skills ADD COLUMN pending_trace_count INTEGER NOT NULL DEFAULT 0"
)
TRACE_TURN_ID_MIGRATION_SQL = f"ALTER TABLE {EXECUTION_TRACES_TABLE} ADD COLUMN turn_id TEXT"
TRACE_TURN_INDEX_SQL = (
    f"CREATE INDEX IF NOT EXISTS idx_l4_traces_turn ON {EXECUTION_TRACES_TABLE}(turn_id, created_at ASC)"
)


async def ensure_procedural_memory_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(PROCEDURAL_MEMORY_SCHEMA_SQL)
    try:
        await db.execute(PENDING_TRACE_COUNT_MIGRATION_SQL)
    except Exception:
        pass
    try:
        await db.execute(TRACE_TURN_ID_MIGRATION_SQL)
    except Exception:
        pass
    await db.execute(TRACE_TURN_INDEX_SQL)
