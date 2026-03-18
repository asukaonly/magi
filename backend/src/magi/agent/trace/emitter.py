"""Helpers for emitting normalized trace-node runtime events."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .contracts import (
    TRACE_NODE_COMPLETED_EVENT_TYPE,
    TRACE_NODE_FAILED_EVENT_TYPE,
    TRACE_NODE_STARTED_EVENT_TYPE,
    TraceNodePayload,
)

EmitRuntimeEvent = Callable[..., Awaitable[None]]


class TraceEventEmitter:
    """Thin adapter around the runtime event emitter for trace-node events."""

    def __init__(self, *, emit_runtime_event: EmitRuntimeEvent) -> None:
        self._emit_runtime_event = emit_runtime_event

    async def emit_node_started(
        self,
        *,
        trace_id: str,
        turn_id: str,
        span_id: str,
        parent_span_id: str | None,
        node_type: str,
        name: str,
        user_id: str,
        session_id: str,
        started_at_ms: int,
        attempt_index: int = 1,
        retry_count: int = 0,
        input: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> None:
        payload = TraceNodePayload(
            trace_id=trace_id,
            turn_id=turn_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            node_type=node_type,
            name=name,
            status="running",
            attempt_index=attempt_index,
            retry_count=retry_count,
            started_at_ms=started_at_ms,
            ended_at_ms=None,
            duration_ms=None,
            input=input or {},
            metrics=metrics or {},
            tags=self._build_tags(user_id=user_id, session_id=session_id, extra=tags),
        )
        await self._emit_runtime_event(
            event_type=TRACE_NODE_STARTED_EVENT_TYPE,
            payload=payload.to_event_payload(),
            correlation_id=span_id,
            success=True,
        )

    async def emit_node_completed(
        self,
        *,
        trace_id: str,
        turn_id: str,
        span_id: str,
        parent_span_id: str | None,
        node_type: str,
        name: str,
        user_id: str,
        session_id: str,
        started_at_ms: int,
        ended_at_ms: int,
        duration_ms: int,
        attempt_index: int = 1,
        retry_count: int = 0,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> None:
        payload = TraceNodePayload(
            trace_id=trace_id,
            turn_id=turn_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            node_type=node_type,
            name=name,
            status="completed",
            attempt_index=attempt_index,
            retry_count=retry_count,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            duration_ms=duration_ms,
            input=input or {},
            output=output or {},
            metrics=metrics or {},
            tags=self._build_tags(user_id=user_id, session_id=session_id, extra=tags),
        )
        await self._emit_runtime_event(
            event_type=TRACE_NODE_COMPLETED_EVENT_TYPE,
            payload=payload.to_event_payload(),
            correlation_id=span_id,
            success=True,
        )

    async def emit_node_failed(
        self,
        *,
        trace_id: str,
        turn_id: str,
        span_id: str,
        parent_span_id: str | None,
        node_type: str,
        name: str,
        user_id: str,
        session_id: str,
        started_at_ms: int,
        ended_at_ms: int,
        duration_ms: int,
        error: dict[str, Any],
        attempt_index: int = 1,
        retry_count: int = 0,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> None:
        payload = TraceNodePayload(
            trace_id=trace_id,
            turn_id=turn_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            node_type=node_type,
            name=name,
            status="failed",
            attempt_index=attempt_index,
            retry_count=retry_count,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            duration_ms=duration_ms,
            input=input or {},
            output=output or {},
            metrics=metrics or {},
            error=error,
            tags=self._build_tags(user_id=user_id, session_id=session_id, extra=tags),
        )
        await self._emit_runtime_event(
            event_type=TRACE_NODE_FAILED_EVENT_TYPE,
            payload=payload.to_event_payload(),
            correlation_id=span_id,
            success=False,
        )

    @staticmethod
    def _build_tags(*, user_id: str, session_id: str, extra: dict[str, Any] | None) -> dict[str, Any]:
        tags = {
            "user_id": user_id,
            "session_id": session_id,
        }
        if isinstance(extra, dict):
            tags.update(extra)
        return tags
