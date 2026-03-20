"""SQLite-backed store for runtime execution traces."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
import time
from typing import Any, TypeVar

import aiosqlite

from .contracts import (
    TraceIntentResolutionRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceToolRecord,
    TraceTurnRecord,
)

T = TypeVar("T")


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

    async def upsert_turn(self, record: TraceTurnRecord) -> None:
        now_ms = max(0, int(record.updated_at_ms or self._now_ms()))
        created_at_ms = max(0, int(record.created_at_ms or now_ms))
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO trace_turns (
                    trace_id,
                    turn_id,
                    session_id,
                    user_id,
                    status,
                    mode,
                    orchestration_id,
                    started_at_ms,
                    ended_at_ms,
                    duration_ms,
                    user_message_preview,
                    response_preview,
                    error_summary,
                    created_at_ms,
                    updated_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    status = excluded.status,
                    mode = excluded.mode,
                    orchestration_id = COALESCE(excluded.orchestration_id, trace_turns.orchestration_id),
                    started_at_ms = MIN(trace_turns.started_at_ms, excluded.started_at_ms),
                    ended_at_ms = COALESCE(excluded.ended_at_ms, trace_turns.ended_at_ms),
                    duration_ms = COALESCE(excluded.duration_ms, trace_turns.duration_ms),
                    user_message_preview = COALESCE(excluded.user_message_preview, trace_turns.user_message_preview),
                    response_preview = COALESCE(excluded.response_preview, trace_turns.response_preview),
                    error_summary = COALESCE(excluded.error_summary, trace_turns.error_summary),
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    record.trace_id,
                    record.turn_id,
                    record.session_id,
                    record.user_id,
                    record.status,
                    record.mode,
                    record.orchestration_id,
                    record.started_at_ms,
                    record.ended_at_ms,
                    record.duration_ms,
                    record.user_message_preview,
                    record.response_preview,
                    record.error_summary,
                    created_at_ms,
                    now_ms,
                ),
            )
            await db.commit()

    async def upsert_span(self, record: TraceSpanRecord) -> None:
        now_ms = max(0, int(record.updated_at_ms or self._now_ms()))
        created_at_ms = max(0, int(record.created_at_ms or now_ms))
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO trace_spans (
                    span_id,
                    trace_id,
                    turn_id,
                    parent_span_id,
                    node_type,
                    name,
                    status,
                    attempt_index,
                    retry_count,
                    iteration,
                    execution_agent_id,
                    result_preview,
                    error_text,
                    started_at_ms,
                    ended_at_ms,
                    duration_ms,
                    created_at_ms,
                    updated_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(span_id) DO UPDATE SET
                    parent_span_id = COALESCE(excluded.parent_span_id, trace_spans.parent_span_id),
                    status = excluded.status,
                    attempt_index = excluded.attempt_index,
                    retry_count = excluded.retry_count,
                    iteration = COALESCE(excluded.iteration, trace_spans.iteration),
                    execution_agent_id = COALESCE(excluded.execution_agent_id, trace_spans.execution_agent_id),
                    result_preview = COALESCE(excluded.result_preview, trace_spans.result_preview),
                    error_text = COALESCE(excluded.error_text, trace_spans.error_text),
                    started_at_ms = MIN(trace_spans.started_at_ms, excluded.started_at_ms),
                    ended_at_ms = COALESCE(excluded.ended_at_ms, trace_spans.ended_at_ms),
                    duration_ms = COALESCE(excluded.duration_ms, trace_spans.duration_ms),
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    record.span_id,
                    record.trace_id,
                    record.turn_id,
                    record.parent_span_id,
                    record.node_type,
                    record.name,
                    record.status,
                    record.attempt_index,
                    record.retry_count,
                    record.iteration,
                    record.execution_agent_id,
                    record.result_preview,
                    record.error_text,
                    record.started_at_ms,
                    record.ended_at_ms,
                    record.duration_ms,
                    created_at_ms,
                    now_ms,
                ),
            )
            await db.commit()

    async def upsert_intent_resolution(self, record: TraceIntentResolutionRecord) -> None:
        await self._upsert_detail(
            """
            INSERT INTO trace_intent_resolutions (
                span_id,
                trace_id,
                turn_id,
                intent,
                execution_mode,
                route_reason,
                selected_tools_json,
                selected_worker_type
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(span_id) DO UPDATE SET
                intent = excluded.intent,
                execution_mode = excluded.execution_mode,
                route_reason = excluded.route_reason,
                selected_tools_json = excluded.selected_tools_json,
                selected_worker_type = excluded.selected_worker_type
            """,
            (
                record.span_id,
                record.trace_id,
                record.turn_id,
                record.intent,
                record.execution_mode,
                record.route_reason,
                record.selected_tools_json,
                record.selected_worker_type,
            ),
        )

    async def upsert_llm_call(self, record: TraceLlmCallRecord) -> None:
        await self._upsert_detail(
            """
            INSERT INTO trace_llm_calls (
                span_id,
                trace_id,
                turn_id,
                provider,
                model,
                input_tokens,
                output_tokens,
                reasoning_tokens,
                cache_read_tokens,
                cache_write_tokens,
                thinking_enabled,
                request_preview,
                response_preview
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(span_id) DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                input_tokens = excluded.input_tokens,
                output_tokens = excluded.output_tokens,
                reasoning_tokens = excluded.reasoning_tokens,
                cache_read_tokens = excluded.cache_read_tokens,
                cache_write_tokens = excluded.cache_write_tokens,
                thinking_enabled = excluded.thinking_enabled,
                request_preview = excluded.request_preview,
                response_preview = excluded.response_preview
            """,
            (
                record.span_id,
                record.trace_id,
                record.turn_id,
                record.provider,
                record.model,
                record.input_tokens,
                record.output_tokens,
                record.reasoning_tokens,
                record.cache_read_tokens,
                record.cache_write_tokens,
                int(record.thinking_enabled),
                record.request_preview,
                record.response_preview,
            ),
        )

    async def upsert_tool_call(self, record: TraceToolRecord) -> None:
        await self._upsert_detail(
            """
            INSERT INTO trace_tools (
                span_id,
                trace_id,
                turn_id,
                tool_name,
                tool_call_id,
                arguments_json,
                success,
                execution_time_ms,
                error_code,
                error_message,
                result_preview
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(span_id) DO UPDATE SET
                tool_name = excluded.tool_name,
                tool_call_id = excluded.tool_call_id,
                arguments_json = excluded.arguments_json,
                success = excluded.success,
                execution_time_ms = excluded.execution_time_ms,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                result_preview = excluded.result_preview
            """,
            (
                record.span_id,
                record.trace_id,
                record.turn_id,
                record.tool_name,
                record.tool_call_id,
                record.arguments_json,
                int(record.success),
                record.execution_time_ms,
                record.error_code,
                record.error_message,
                record.result_preview,
            ),
        )

    async def get_turn(self, turn_id: str) -> TraceTurnRecord | None:
        row = await self._fetchone(
            "SELECT * FROM trace_turns WHERE turn_id = ?",
            (turn_id,),
        )
        return self._row_to_record(TraceTurnRecord, row)

    async def get_span(self, span_id: str) -> TraceSpanRecord | None:
        row = await self._fetchone(
            "SELECT * FROM trace_spans WHERE span_id = ?",
            (span_id,),
        )
        return self._row_to_record(TraceSpanRecord, row)

    async def get_intent_resolution(self, span_id: str) -> TraceIntentResolutionRecord | None:
        row = await self._fetchone(
            "SELECT * FROM trace_intent_resolutions WHERE span_id = ?",
            (span_id,),
        )
        return self._row_to_record(TraceIntentResolutionRecord, row)

    async def get_llm_call(self, span_id: str) -> TraceLlmCallRecord | None:
        row = await self._fetchone(
            "SELECT * FROM trace_llm_calls WHERE span_id = ?",
            (span_id,),
        )
        record = self._row_to_record(TraceLlmCallRecord, row)
        if record is not None:
            record.thinking_enabled = bool(record.thinking_enabled)
        return record

    async def get_tool_call(self, span_id: str) -> TraceToolRecord | None:
        row = await self._fetchone(
            "SELECT * FROM trace_tools WHERE span_id = ?",
            (span_id,),
        )
        record = self._row_to_record(TraceToolRecord, row)
        if record is not None:
            record.success = bool(record.success)
        return record

    async def _upsert_detail(self, sql: str, params: tuple[Any, ...]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, params)
            await db.commit()

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            return await cursor.fetchone()

    @staticmethod
    def _row_to_record(record_type: type[T], row: aiosqlite.Row | None) -> T | None:
        if row is None:
            return None
        values = {
            field.name: row[field.name]
            for field in fields(record_type)
            if field.name in row.keys()
        }
        return record_type(**values)

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)
