"""Runtime trace SQLite schema and migrations."""

from __future__ import annotations

import aiosqlite


RUNTIME_TRACE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trace_turns (
    trace_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    orchestration_id TEXT,
    started_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER,
    duration_ms INTEGER,
    user_message_preview TEXT,
    response_preview TEXT,
    error_summary TEXT,
    continued_from_turn_id TEXT,
    continued_from_trace_id TEXT,
    superseded_by_turn_id TEXT,
    supersession_reason TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_turns_session_turn
    ON trace_turns(session_id, turn_id);
CREATE INDEX IF NOT EXISTS idx_trace_turns_user_updated
    ON trace_turns(user_id, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS trace_spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    parent_span_id TEXT,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_index INTEGER NOT NULL DEFAULT 1,
    retry_count INTEGER NOT NULL DEFAULT 0,
    iteration INTEGER,
    execution_agent_id TEXT,
    result_preview TEXT,
    error_text TEXT,
    started_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER,
    duration_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_parent_started
    ON trace_spans(trace_id, parent_span_id, started_at_ms);
CREATE INDEX IF NOT EXISTS idx_trace_spans_turn_started
    ON trace_spans(turn_id, started_at_ms);
CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_node_type
    ON trace_spans(trace_id, node_type);

CREATE TABLE IF NOT EXISTS trace_intent_resolutions (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    intent TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    route_reason TEXT,
    selected_tools_json TEXT NOT NULL,
    selected_worker_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_trace_intent_trace
    ON trace_intent_resolutions(trace_id);

CREATE TABLE IF NOT EXISTS trace_llm_calls (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    thinking_enabled INTEGER NOT NULL DEFAULT 0,
    request_preview TEXT,
    response_preview TEXT
);
CREATE INDEX IF NOT EXISTS idx_trace_llm_calls_trace
    ON trace_llm_calls(trace_id);

CREATE TABLE IF NOT EXISTS trace_tools (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_call_id TEXT,
    arguments_json TEXT NOT NULL,
    success INTEGER NOT NULL,
    execution_time_ms INTEGER,
    error_code TEXT,
    error_message TEXT,
    result_preview TEXT
);
CREATE INDEX IF NOT EXISTS idx_trace_tools_trace
    ON trace_tools(trace_id);

CREATE TABLE IF NOT EXISTS runtime_notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_notifications_created
    ON runtime_notifications(notification_id ASC);

CREATE TABLE IF NOT EXISTS runtime_heartbeats (
    role TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    started_at_ms INTEGER NOT NULL,
    last_seen_at_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    queue_backlog INTEGER NOT NULL DEFAULT 0,
    active_turns INTEGER NOT NULL DEFAULT 0,
    active_workers INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS plugin_ingress_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL,
    producer TEXT NOT NULL,
    plugin_target TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    cursor_key TEXT,
    status TEXT NOT NULL,
    claimed_by TEXT,
    claimed_at_ms INTEGER,
    processed_at_ms INTEGER,
    last_error TEXT,
    created_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plugin_ingress_events_status_created
    ON plugin_ingress_events(status, created_at_ms ASC, event_id ASC);
CREATE INDEX IF NOT EXISTS idx_plugin_ingress_events_target_type_status
    ON plugin_ingress_events(plugin_target, event_type, status, created_at_ms ASC, event_id ASC);
"""


async def ensure_runtime_trace_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(RUNTIME_TRACE_SCHEMA_SQL)
    await ensure_trace_turn_columns(db)
    await ensure_trace_detail_columns(db)


async def ensure_trace_turn_columns(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(trace_turns)")
    rows = await cursor.fetchall()
    column_names = {str(row[1]) for row in rows}
    if "continued_from_turn_id" not in column_names:
        await db.execute("ALTER TABLE trace_turns ADD COLUMN continued_from_turn_id TEXT")
    if "continued_from_trace_id" not in column_names:
        await db.execute("ALTER TABLE trace_turns ADD COLUMN continued_from_trace_id TEXT")
    if "superseded_by_turn_id" not in column_names:
        await db.execute("ALTER TABLE trace_turns ADD COLUMN superseded_by_turn_id TEXT")
    if "supersession_reason" not in column_names:
        await db.execute("ALTER TABLE trace_turns ADD COLUMN supersession_reason TEXT")


async def ensure_trace_detail_columns(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(trace_llm_calls)")
    rows = await cursor.fetchall()
    llm_columns = {str(row[1]) for row in rows}
    if "thinking_content" not in llm_columns:
        await db.execute("ALTER TABLE trace_llm_calls ADD COLUMN thinking_content TEXT")

    cursor = await db.execute("PRAGMA table_info(trace_tools)")
    rows = await cursor.fetchall()
    tool_columns = {str(row[1]) for row in rows}
    if "result_json" not in tool_columns:
        await db.execute("ALTER TABLE trace_tools ADD COLUMN result_json TEXT")