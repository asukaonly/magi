"""Subscribes to SpanCompleted and projects into 5 runtime_trace tables.

trace_spans is ALWAYS written. A node_type-specific sub-table is OPTIONALLY
written per the dispatch table. Errors in any handler are logged and isolated;
they don't propagate back to the bus.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.events.payload_helpers import expect_payload, PayloadTypeError
from magi.runtime_trace.contracts import (
    TraceIntentResolutionRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceToolRecord,
    TraceTurnRecord,
)

logger = logging.getLogger(__name__)


class RuntimeTraceSubscriber:
    """Subscribe to SpanCompleted events; project into runtime_trace tables.

    trace_spans is always written. Sub-tables (trace_tools, trace_llm_calls,
    trace_intent_resolutions, trace_turns) are written only when node_type
    matches the dispatch table. Handler errors are caught and logged so a
    single bad event cannot kill the subscription.
    """

    def __init__(self, *, event_bus, trace_store) -> None:
        self._bus = event_bus
        self._store = trace_store
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()
        self._serialize_lock = asyncio.Lock()
        self._dispatch: dict[str, Callable[[SpanCompleted], Awaitable[None]]] = {
            "tool_invocation": self._record_tool_call,
            "llm_call": self._record_llm_call,
            "intent_resolution": self._record_intent_resolution,
            "turn_record": self._record_turn,
        }

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SPAN_COMPLETED, self._on_span_completed
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("unsubscribe failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_span_completed(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SpanCompleted)
        except PayloadTypeError:
            logger.exception("malformed SpanCompleted payload")
            return
        task = asyncio.create_task(self._serialized_project(payload))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _serialized_project(self, p: SpanCompleted) -> None:
        # Serialize per-subscriber so events that share span_id (e.g., the
        # base span row + a sub-table row published in sequence) project in
        # the order they were published.
        async with self._serialize_lock:
            await self._safe_project(p)

    async def _safe_project(self, p: SpanCompleted) -> None:
        try:
            await self._record_span(p)
        except Exception:
            logger.exception("trace_spans projection failed: span=%s", p.span_id)
        handler = self._dispatch.get(p.node_type)
        if handler is not None:
            try:
                await handler(p)
            except Exception:
                logger.exception(
                    "runtime_trace sub-table projection failed: span=%s node_type=%s",
                    p.span_id,
                    p.node_type,
                )

    async def _record_span(self, p: SpanCompleted) -> None:
        attrs = p.attributes or {}
        record = TraceSpanRecord(
            span_id=p.span_id,
            trace_id=p.trace_id,
            turn_id=p.turn_id,
            parent_span_id=p.parent_span_id,
            node_type=p.node_type,
            name=p.name,
            status=p.status,
            attempt_index=int(attrs.get("attempt_index", 1)),
            retry_count=int(attrs.get("retry_count", 0)),
            iteration=attrs.get("iteration"),
            execution_agent_id=attrs.get("execution_agent_id"),
            result_preview=p.result_preview,
            error_text=(p.error.message if p.error else None),
            run_id=attrs.get("run_id"),
            run_revision=int(attrs.get("run_revision", 0)),
            started_at_ms=p.started_at_ms,
            ended_at_ms=p.ended_at_ms,
            duration_ms=p.duration_ms,
            created_at_ms=p.started_at_ms,
            updated_at_ms=p.ended_at_ms,
        )
        await self._store.upsert_span(record)

    async def _record_tool_call(self, p: SpanCompleted) -> None:
        attrs = p.attributes or {}
        record = TraceToolRecord(
            span_id=p.span_id,
            trace_id=p.trace_id,
            turn_id=p.turn_id or "",
            tool_name=str(attrs.get("tool_name") or p.name),
            tool_call_id=attrs.get("tool_call_id"),
            arguments_json=str(attrs.get("arguments_json") or "{}"),
            success=bool(attrs.get("success", p.status == "ok")),
            execution_time_ms=attrs.get("execution_time_ms"),
            error_code=attrs.get("error_code"),
            error_message=attrs.get("error_message")
            or (p.error.message if p.error else None),
            result_preview=attrs.get("result_preview") or p.result_preview,
            result_json=attrs.get("result_json"),
        )
        await self._store.upsert_tool_call(record)

    async def _record_llm_call(self, p: SpanCompleted) -> None:
        attrs = p.attributes or {}
        record = TraceLlmCallRecord(
            span_id=p.span_id,
            trace_id=p.trace_id,
            turn_id=p.turn_id or "",
            provider=str(attrs.get("provider") or ""),
            model=str(attrs.get("model") or p.name),
            input_tokens=int(attrs.get("input_tokens", 0)),
            output_tokens=int(attrs.get("output_tokens", 0)),
            reasoning_tokens=int(attrs.get("reasoning_tokens", 0)),
            cache_read_tokens=int(attrs.get("cache_read_tokens", 0)),
            cache_write_tokens=int(attrs.get("cache_write_tokens", 0)),
            thinking_enabled=bool(attrs.get("thinking_enabled", False)),
            thinking_depth=str(attrs.get("thinking_depth", "none")),
            request_preview=attrs.get("request_preview"),
            response_preview=attrs.get("response_preview"),
            thinking_content=attrs.get("thinking_content"),
        )
        await self._store.upsert_llm_call(record)

    async def _record_intent_resolution(self, p: SpanCompleted) -> None:
        attrs = p.attributes or {}
        record = TraceIntentResolutionRecord(
            span_id=p.span_id,
            trace_id=p.trace_id,
            turn_id=p.turn_id or "",
            intent=str(attrs.get("intent") or p.name),
            execution_mode=str(attrs.get("execution_mode") or ""),
            route_reason=attrs.get("route_reason"),
            selected_tools_json=str(attrs.get("selected_tools_json") or "[]"),
            selected_worker_type=attrs.get("selected_worker_type"),
        )
        await self._store.upsert_intent_resolution(record)

    async def _record_turn(self, p: SpanCompleted) -> None:
        attrs = p.attributes or {}
        record = TraceTurnRecord(
            trace_id=p.trace_id,
            turn_id=str(attrs.get("turn_id") or p.turn_id or p.name),
            session_id=str(attrs.get("session_id") or ""),
            user_id=str(attrs.get("user_id") or ""),
            status=str(attrs.get("status") or p.status),
            mode=str(attrs.get("mode") or ""),
            orchestration_id=attrs.get("orchestration_id"),
            started_at_ms=int(attrs.get("started_at_ms", p.started_at_ms)),
            ended_at_ms=attrs.get("ended_at_ms", p.ended_at_ms),
            duration_ms=attrs.get("duration_ms", p.duration_ms),
            user_message_preview=attrs.get("user_message_preview"),
            response_preview=attrs.get("response_preview") or p.result_preview,
            error_summary=attrs.get("error_summary")
            or (p.error.message if p.error else None),
            run_id=attrs.get("run_id"),
            run_revision=int(attrs.get("run_revision", 0)),
            continued_from_turn_id=attrs.get("continued_from_turn_id"),
            continued_from_trace_id=attrs.get("continued_from_trace_id"),
            superseded_by_turn_id=attrs.get("superseded_by_turn_id"),
            supersession_reason=attrs.get("supersession_reason"),
            created_at_ms=int(attrs.get("created_at_ms", p.started_at_ms)),
            updated_at_ms=int(attrs.get("updated_at_ms", p.ended_at_ms)),
        )
        await self._store.upsert_turn(record)
