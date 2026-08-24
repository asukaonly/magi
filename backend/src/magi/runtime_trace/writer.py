"""Semantic write facade for runtime trace persistence."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from magi.events.domain_payloads import SpanCompleted

from .contracts import (
    TraceIntentResolutionRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceToolRecord,
    TraceTurnRecord,
)


class RuntimeTraceWriter:
    """Centralize runtime trace row construction and persistence.

    Runtime code can still create live running spans, but all writes should pass
    through this facade instead of calling RuntimeTraceStore upsert methods from
    business modules directly.
    """

    def __init__(self, trace_store: Any) -> None:
        self._store = trace_store
        self._dispatch: dict[str, Callable[[SpanCompleted], Awaitable[None]]] = {
            "tool_invocation": self._record_tool_call_from_span,
            "llm_call": self._record_llm_call_from_span,
            "intent_resolution": self._record_intent_resolution_from_span,
            "turn_record": self._record_turn_from_span,
        }

    async def project_span_completed(self, payload: SpanCompleted) -> None:
        """Project a SpanCompleted event into canonical runtime trace rows."""
        if payload.node_type != "turn_record":
            await self.record_span(self._span_record_from_payload(payload))
        handler = self._dispatch.get(payload.node_type)
        if handler is not None:
            await handler(payload)

    async def record_turn(self, record: TraceTurnRecord) -> None:
        await self._store.upsert_turn(record)

    async def record_span(self, record: TraceSpanRecord) -> None:
        await self._store.upsert_span(record)

    async def record_intent_resolution(self, record: TraceIntentResolutionRecord) -> None:
        await self._store.upsert_intent_resolution(record)

    async def record_llm_call(self, record: TraceLlmCallRecord) -> None:
        await self._store.upsert_llm_call(record)

    async def record_tool_call(self, record: TraceToolRecord) -> None:
        await self._store.upsert_tool_call(record)

    @staticmethod
    def _int_attr(attrs: dict[str, Any], *keys: str, default: int = 0) -> int:
        for key in keys:
            value = attrs.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return default

    @staticmethod
    def _bool_attr(attrs: dict[str, Any], *keys: str, default: bool = False) -> bool:
        for key in keys:
            value = attrs.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"1", "true", "yes", "y", "on", "ok", "success", "completed"}:
                    return True
                if normalized in {
                    "0",
                    "false",
                    "no",
                    "n",
                    "off",
                    "error",
                    "failed",
                    "failure",
                    "cancelled",
                }:
                    return False
        return default

    def _span_record_from_payload(self, payload: SpanCompleted) -> TraceSpanRecord:
        attrs = payload.attributes or {}
        return TraceSpanRecord(
            span_id=payload.span_id,
            trace_id=payload.trace_id,
            turn_id=payload.turn_id or "",
            parent_span_id=payload.parent_span_id,
            node_type=payload.node_type,
            name=payload.name,
            status=payload.status,
            attempt_index=self._int_attr(attrs, "attempt_index", default=1),
            retry_count=self._int_attr(attrs, "retry_count"),
            iteration=attrs.get("iteration"),
            execution_agent_id=attrs.get("execution_agent_id"),
            result_preview=payload.result_preview,
            error_text=(payload.error.message if payload.error else None),
            input_preview=attrs.get("input_preview") or attrs.get("request_preview"),
            output_preview=attrs.get("output_preview") or attrs.get("response_preview"),
            run_id=attrs.get("run_id"),
            run_revision=self._int_attr(attrs, "run_revision"),
            started_at_ms=payload.started_at_ms,
            ended_at_ms=payload.ended_at_ms,
            duration_ms=payload.duration_ms,
            created_at_ms=payload.started_at_ms,
            updated_at_ms=payload.ended_at_ms,
        )

    async def _record_tool_call_from_span(self, payload: SpanCompleted) -> None:
        attrs = payload.attributes or {}
        if not attrs.get("tool_name"):
            return
        await self.record_tool_call(
            TraceToolRecord(
                span_id=payload.span_id,
                trace_id=payload.trace_id,
                turn_id=payload.turn_id or "",
                tool_name=str(attrs.get("tool_name") or payload.name),
                tool_call_id=attrs.get("tool_call_id"),
                arguments_json=str(attrs.get("arguments_json") or "{}"),
                success=self._bool_attr(
                    attrs,
                    "success",
                    default=payload.status in {"ok", "completed", "success"},
                ),
                execution_time_ms=attrs.get("execution_time_ms"),
                error_code=attrs.get("error_code"),
                error_message=attrs.get("error_message")
                or (payload.error.message if payload.error else None),
                result_preview=attrs.get("result_preview") or payload.result_preview,
                result_json=attrs.get("result_json"),
            )
        )

    async def _record_llm_call_from_span(self, payload: SpanCompleted) -> None:
        attrs = payload.attributes or {}
        if not attrs.get("model") and not attrs.get("provider"):
            return
        await self.record_llm_call(
            TraceLlmCallRecord(
                span_id=payload.span_id,
                trace_id=payload.trace_id,
                turn_id=payload.turn_id or "",
                provider=str(attrs.get("provider") or ""),
                model=str(attrs.get("model") or payload.name),
                input_tokens=self._int_attr(attrs, "input_tokens", "prompt_tokens"),
                output_tokens=self._int_attr(attrs, "output_tokens", "completion_tokens"),
                reasoning_tokens=self._int_attr(attrs, "reasoning_tokens"),
                cache_read_tokens=self._int_attr(attrs, "cache_read_tokens"),
                cache_write_tokens=self._int_attr(attrs, "cache_write_tokens"),
                thinking_enabled=self._bool_attr(attrs, "thinking_enabled"),
                thinking_depth=str(attrs.get("thinking_depth", "none")),
                request_preview=attrs.get("request_preview"),
                response_preview=attrs.get("response_preview"),
                thinking_content=attrs.get("thinking_content"),
            )
        )

    async def _record_intent_resolution_from_span(self, payload: SpanCompleted) -> None:
        attrs = payload.attributes or {}
        if not attrs.get("intent") and not attrs.get("execution_mode"):
            return
        await self.record_intent_resolution(
            TraceIntentResolutionRecord(
                span_id=payload.span_id,
                trace_id=payload.trace_id,
                turn_id=payload.turn_id or "",
                intent=str(attrs.get("intent") or payload.name),
                execution_mode=str(attrs.get("execution_mode") or ""),
                route_reason=attrs.get("route_reason"),
                selected_tools_json=str(attrs.get("selected_tools_json") or "[]"),
                selected_worker_type=attrs.get("selected_worker_type"),
            )
        )

    async def _record_turn_from_span(self, payload: SpanCompleted) -> None:
        attrs = payload.attributes or {}
        await self.record_turn(
            TraceTurnRecord(
                trace_id=payload.trace_id,
                turn_id=str(attrs.get("turn_id") or payload.turn_id or payload.name),
                session_id=str(attrs.get("session_id") or ""),
                user_id=str(attrs.get("user_id") or ""),
                status=str(attrs.get("status") or payload.status),
                mode=str(attrs.get("mode") or ""),
                started_at_ms=self._int_attr(attrs, "started_at_ms", default=payload.started_at_ms),
                ended_at_ms=attrs.get("ended_at_ms", payload.ended_at_ms),
                duration_ms=attrs.get("duration_ms", payload.duration_ms),
                user_message_preview=attrs.get("user_message_preview"),
                response_preview=attrs.get("response_preview") or payload.result_preview,
                error_summary=attrs.get("error_summary")
                or (payload.error.message if payload.error else None),
                run_id=attrs.get("run_id"),
                run_revision=self._int_attr(attrs, "run_revision"),
                continued_from_turn_id=attrs.get("continued_from_turn_id"),
                continued_from_trace_id=attrs.get("continued_from_trace_id"),
                superseded_by_turn_id=attrs.get("superseded_by_turn_id"),
                supersession_reason=attrs.get("supersession_reason"),
                created_at_ms=self._int_attr(attrs, "created_at_ms", default=payload.started_at_ms),
                updated_at_ms=self._int_attr(attrs, "updated_at_ms", default=payload.ended_at_ms),
            )
        )


__all__ = ["RuntimeTraceWriter"]
