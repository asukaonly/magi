"""Trace turn, span, and detail row persistence."""

from __future__ import annotations

from typing import Any, TypeVar

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .contracts import (
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceToolRecord,
    TraceTurnRecord,
)

T = TypeVar("T")


_UPSERT_SPAN_SQL = """
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
        input_preview,
        output_preview,
        run_id,
        run_revision,
        started_at_ms,
        ended_at_ms,
        duration_ms,
        created_at_ms,
        updated_at_ms
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(span_id) DO UPDATE SET
        parent_span_id = COALESCE(excluded.parent_span_id, trace_spans.parent_span_id),
        status = excluded.status,
        attempt_index = excluded.attempt_index,
        retry_count = excluded.retry_count,
        iteration = COALESCE(excluded.iteration, trace_spans.iteration),
        execution_agent_id = COALESCE(excluded.execution_agent_id, trace_spans.execution_agent_id),
        result_preview = COALESCE(excluded.result_preview, trace_spans.result_preview),
        error_text = COALESCE(excluded.error_text, trace_spans.error_text),
        input_preview = COALESCE(excluded.input_preview, trace_spans.input_preview),
        output_preview = COALESCE(excluded.output_preview, trace_spans.output_preview),
        run_id = COALESCE(excluded.run_id, trace_spans.run_id),
        run_revision = MAX(trace_spans.run_revision, excluded.run_revision),
        started_at_ms = MIN(trace_spans.started_at_ms, excluded.started_at_ms),
        ended_at_ms = COALESCE(excluded.ended_at_ms, trace_spans.ended_at_ms),
        duration_ms = COALESCE(excluded.duration_ms, trace_spans.duration_ms),
        updated_at_ms = excluded.updated_at_ms
"""


_UPSERT_TURN_SQL = """
    INSERT INTO trace_turns (
        trace_id,
        turn_id,
        session_id,
        user_id,
        status,
        mode,
        started_at_ms,
        ended_at_ms,
        duration_ms,
        user_message_preview,
        response_preview,
        error_summary,
        run_id,
        run_revision,
        continued_from_turn_id,
        continued_from_trace_id,
        superseded_by_turn_id,
        supersession_reason,
        created_at_ms,
        updated_at_ms
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(trace_id) DO UPDATE SET
        status = excluded.status,
        mode = excluded.mode,
        started_at_ms = MIN(trace_turns.started_at_ms, excluded.started_at_ms),
        ended_at_ms = COALESCE(excluded.ended_at_ms, trace_turns.ended_at_ms),
        duration_ms = COALESCE(excluded.duration_ms, trace_turns.duration_ms),
        user_message_preview = COALESCE(excluded.user_message_preview, trace_turns.user_message_preview),
        response_preview = COALESCE(excluded.response_preview, trace_turns.response_preview),
        error_summary = COALESCE(excluded.error_summary, trace_turns.error_summary),
        run_id = COALESCE(excluded.run_id, trace_turns.run_id),
        run_revision = MAX(trace_turns.run_revision, excluded.run_revision),
        continued_from_turn_id = COALESCE(excluded.continued_from_turn_id, trace_turns.continued_from_turn_id),
        continued_from_trace_id = COALESCE(excluded.continued_from_trace_id, trace_turns.continued_from_trace_id),
        superseded_by_turn_id = COALESCE(excluded.superseded_by_turn_id, trace_turns.superseded_by_turn_id),
        supersession_reason = COALESCE(excluded.supersession_reason, trace_turns.supersession_reason),
        updated_at_ms = excluded.updated_at_ms
"""


def _turn_params(
    record: TraceTurnRecord,
    *,
    created_at_ms: int,
    now_ms: int,
) -> tuple[Any, ...]:
    return (
        record.trace_id,
        record.turn_id,
        record.session_id,
        record.user_id,
        record.status,
        record.mode,
        record.started_at_ms,
        record.ended_at_ms,
        record.duration_ms,
        record.user_message_preview,
        record.response_preview,
        record.error_summary,
        record.run_id,
        record.run_revision,
        record.continued_from_turn_id,
        record.continued_from_trace_id,
        record.superseded_by_turn_id,
        record.supersession_reason,
        created_at_ms,
        now_ms,
    )


def _span_params(
    record: TraceSpanRecord,
    *,
    created_at_ms: int,
    now_ms: int,
) -> tuple[Any, ...]:
    return (
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
        record.input_preview,
        record.output_preview,
        record.run_id,
        record.run_revision,
        record.started_at_ms,
        record.ended_at_ms,
        record.duration_ms,
        created_at_ms,
        now_ms,
    )


class TraceRecordPersistenceMixin:
    """Persist trace turns, spans, and span detail rows."""

    db_path: str

    async def _upsert_detail(self, sql: str, params: tuple[Any, ...]) -> None:
        raise NotImplementedError

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        raise NotImplementedError

    def _row_to_record(self, record_type: type[T], row: aiosqlite.Row | None) -> T | None:
        raise NotImplementedError

    @staticmethod
    def _now_ms() -> int:
        raise NotImplementedError

    async def upsert_turn(self, record: TraceTurnRecord) -> None:
        now_ms = max(0, int(record.updated_at_ms or self._now_ms()))
        created_at_ms = max(0, int(record.created_at_ms or now_ms))
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                _UPSERT_TURN_SQL,
                _turn_params(record, created_at_ms=created_at_ms, now_ms=now_ms),
            )
            await db.commit()

    async def upsert_span(self, record: TraceSpanRecord) -> None:
        now_ms = max(0, int(record.updated_at_ms or self._now_ms()))
        created_at_ms = max(0, int(record.created_at_ms or now_ms))
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                _UPSERT_SPAN_SQL,
                _span_params(record, created_at_ms=created_at_ms, now_ms=now_ms),
            )
            await db.commit()

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
                thinking_depth,
                request_preview,
                response_preview,
                thinking_content
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(span_id) DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                input_tokens = excluded.input_tokens,
                output_tokens = excluded.output_tokens,
                reasoning_tokens = excluded.reasoning_tokens,
                cache_read_tokens = excluded.cache_read_tokens,
                cache_write_tokens = excluded.cache_write_tokens,
                thinking_enabled = excluded.thinking_enabled,
                thinking_depth = excluded.thinking_depth,
                request_preview = excluded.request_preview,
                response_preview = excluded.response_preview,
                thinking_content = excluded.thinking_content
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
                record.thinking_depth,
                record.request_preview,
                record.response_preview,
                record.thinking_content,
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
                result_preview,
                result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(span_id) DO UPDATE SET
                tool_name = excluded.tool_name,
                tool_call_id = excluded.tool_call_id,
                arguments_json = excluded.arguments_json,
                success = excluded.success,
                execution_time_ms = excluded.execution_time_ms,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                result_preview = excluded.result_preview,
                result_json = excluded.result_json
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
                record.result_json,
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

    async def get_tool_execution_stats(
        self,
        tool_names: list[str] | None = None,
    ) -> dict[str, dict[str, float | int]]:
        await self.initialize()
        params: list[object] = []
        where_clause = ""
        if tool_names:
            normalized_names = [str(name).strip() for name in tool_names if str(name).strip()]
            if not normalized_names:
                return {}
            where_clause = f"WHERE tool_name IN ({', '.join('?' for _ in normalized_names)})"
            params.extend(normalized_names)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT
                    tool_name,
                    COUNT(*) AS total_calls,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
                    SUM(CASE WHEN success = 1 THEN 0 ELSE 1 END) AS failed_calls,
                    AVG(execution_time_ms) AS avg_execution_time_ms
                FROM trace_tools
                {where_clause}
                GROUP BY tool_name
                """,
                tuple(params),
            )
            rows = await cursor.fetchall()
        stats: dict[str, dict[str, float | int]] = {}
        for row in rows:
            total_calls = int(row["total_calls"] or 0)
            successful_calls = int(row["successful_calls"] or 0)
            failed_calls = int(row["failed_calls"] or 0)
            stats[str(row["tool_name"])] = {
                "total_calls": total_calls,
                "successful_calls": successful_calls,
                "failed_calls": failed_calls,
                "success_rate": (float(successful_calls / total_calls) if total_calls else 0.0),
                "avg_execution_time_ms": float(row["avg_execution_time_ms"] or 0.0),
            }
        return stats
