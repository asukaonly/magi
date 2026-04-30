"""LLM trace persistence helpers for chat post-processing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .....agent.trace import now_wall_ms
from .....runtime_trace import TraceLlmCallRecord, TraceSpanRecord


class ChatPostprocessLlmTraceMixin:
    """Persist LLM call trace records produced during chat execution."""

    _runtime_trace_store: Any
    _build_trace_id: Callable[[str], str]
    _build_root_span_id: Callable[[str], str]
    _build_span_id: Callable[[str, str], str]

    async def _ensure_turn_trace_started(
        self,
        *,
        trace_id: str,
        turn_id: str,
        user_id: str,
        session_id: str,
        started_at_ms: int,
        user_message: str,
        mode: str,
    ) -> None: ...

    async def _emit_loop_llm_trace(
        self,
        *,
        event_emitter: Any,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        stage: str,
        iteration: Any,
        execution_agent_id: Any,
        llm_trace: Any,
        response_preview: Any,
        tool_count: Any,
        tool_names: Any,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id or not isinstance(llm_trace, dict):
            return
        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = now_wall_ms()
        started_at_ms = max(0, ended_at_ms - duration_ms)
        _ = (event_emitter, user_id, session_id, tool_count, tool_names, response_preview, execution_agent_id)
        if self._runtime_trace_store is None:
            return
        span_id = self._build_span_id(
            normalized_turn_id,
            f"llm_call:{stage}:{int(iteration or 0)}",
        )
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=self._build_span_id(normalized_turn_id, f"iteration:{int(iteration or 0)}"),
                node_type="llm_call",
                name="Function-calling LLM call",
                status="completed",
                iteration=int(iteration or 0),
                execution_agent_id=str(execution_agent_id or "") or None,
                result_preview=str(response_preview or "")[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_llm_call(
            TraceLlmCallRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                request_preview=str(llm_trace.get("request_preview") or "")[:240] or None,
                response_preview=str(response_preview or "")[:240] or None,
            )
        )

    async def _emit_result_llm_trace(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        llm_trace: Any,
        started_at_ms: int,
        user_message: str,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id or not isinstance(llm_trace, dict) or not llm_trace:
            return
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=normalized_turn_id,
            user_id=user_id,
            session_id=session_id,
            started_at_ms=started_at_ms,
            user_message=user_message,
            mode="direct_llm",
        )
        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = max(started_at_ms, started_at_ms + duration_ms)
        span_id = self._build_span_id(normalized_turn_id, "llm_call:direct")
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="llm_call",
                name="Main LLM call",
                status="completed",
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_llm_call(
            TraceLlmCallRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                request_preview=(user_message or "")[:240] or None,
            )
        )


__all__ = ["ChatPostprocessLlmTraceMixin"]
