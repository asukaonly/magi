"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trace_turns (
    trace_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    orchestration_id TEXT,
    run_id TEXT,
    run_revision INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS trace_spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    turn_id TEXT,
    parent_span_id TEXT,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_index INTEGER NOT NULL DEFAULT 1,
    retry_count INTEGER NOT NULL DEFAULT 0,
    iteration INTEGER,
    execution_agent_id TEXT,
    run_id TEXT,
    run_revision INTEGER NOT NULL DEFAULT 0,
    input_preview TEXT,
    output_preview TEXT,
    result_preview TEXT,
    error_text TEXT,
    started_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER,
    duration_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

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
    thinking_depth TEXT NOT NULL DEFAULT 'none',
    thinking_content TEXT,
    request_preview TEXT,
    response_preview TEXT
);

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
    result_preview TEXT,
    result_json TEXT
);

CREATE TABLE IF NOT EXISTS runtime_notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    run_id TEXT,
    run_revision INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
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

CREATE TABLE IF NOT EXISTS user_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default_user',
    kind TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'unread',
    created_at_ms INTEGER NOT NULL,
    read_at_ms INTEGER,
    actioned_at_ms INTEGER,
    dismissed_at_ms INTEGER,
    dismiss_kind TEXT
);

CREATE INDEX IF NOT EXISTS idx_trace_turns_session_turn
    ON trace_turns(session_id, turn_id);

CREATE INDEX IF NOT EXISTS idx_trace_turns_user_updated
    ON trace_turns(user_id, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_parent_started
    ON trace_spans(trace_id, parent_span_id, started_at_ms);

CREATE INDEX IF NOT EXISTS idx_trace_spans_turn_started
    ON trace_spans(turn_id, started_at_ms);

CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_node_type
    ON trace_spans(trace_id, node_type);

CREATE INDEX IF NOT EXISTS idx_trace_intent_trace
    ON trace_intent_resolutions(trace_id);

CREATE INDEX IF NOT EXISTS idx_trace_llm_calls_trace
    ON trace_llm_calls(trace_id);

CREATE INDEX IF NOT EXISTS idx_trace_tools_trace
    ON trace_tools(trace_id);

CREATE INDEX IF NOT EXISTS idx_plugin_ingress_events_status_created
    ON plugin_ingress_events(status, created_at_ms ASC, event_id ASC);

CREATE INDEX IF NOT EXISTS idx_plugin_ingress_events_target_type_status
    ON plugin_ingress_events(plugin_target, event_type, status, created_at_ms ASC, event_id ASC);

CREATE INDEX IF NOT EXISTS idx_runtime_notifications_user_session
    ON runtime_notifications(user_id, session_id);

CREATE INDEX IF NOT EXISTS idx_user_notifications_feed
    ON user_notifications(user_id, created_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_user_notifications_dedup
    ON user_notifications(user_id, kind, dedupe_key);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_user_notifications_dedup;

DROP INDEX IF EXISTS idx_user_notifications_feed;

DROP INDEX IF EXISTS idx_runtime_notifications_user_session;

DROP INDEX IF EXISTS idx_plugin_ingress_events_target_type_status;

DROP INDEX IF EXISTS idx_plugin_ingress_events_status_created;

DROP INDEX IF EXISTS idx_trace_tools_trace;

DROP INDEX IF EXISTS idx_trace_llm_calls_trace;

DROP INDEX IF EXISTS idx_trace_intent_trace;

DROP INDEX IF EXISTS idx_trace_spans_trace_node_type;

DROP INDEX IF EXISTS idx_trace_spans_turn_started;

DROP INDEX IF EXISTS idx_trace_spans_trace_parent_started;

DROP INDEX IF EXISTS idx_trace_turns_user_updated;

DROP INDEX IF EXISTS idx_trace_turns_session_turn;

DROP TABLE IF EXISTS user_notifications;

DROP TABLE IF EXISTS plugin_ingress_events;

DROP TABLE IF EXISTS runtime_notifications;

DROP TABLE IF EXISTS trace_tools;

DROP TABLE IF EXISTS trace_llm_calls;

DROP TABLE IF EXISTS trace_intent_resolutions;

DROP TABLE IF EXISTS trace_spans;

DROP TABLE IF EXISTS trace_turns;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
