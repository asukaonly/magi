"""SQLite-backed store for runtime execution traces."""

from __future__ import annotations

from pathlib import Path

import aiosqlite


class RuntimeTraceStore:
    """Persist runtime trace data in a dedicated SQLite database."""

    def __init__(self, *, db_path: str = "~/.magi/data/runtime_trace.db") -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
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
                """
            )
            await db.commit()
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False
