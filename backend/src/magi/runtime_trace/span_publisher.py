"""Helpers to publish SpanCompleted events without using the with-context machinery.

The chat post-process and worker-trace paths build records ad-hoc after the fact;
they don't have a 'with start_span' scope to wrap. They use this module to
construct + publish SpanCompleted directly.

Phase 6 will use this helper to migrate worker_trace.py the same way.
"""
from __future__ import annotations
import logging
import uuid
from typing import Any, Mapping, Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted, ToolError

logger = logging.getLogger(__name__)


def resolve_event_bus(*, fallback: Any = None) -> Any | None:
    """Resolve a message bus for trace publishing.

    Prefer the explicit fallback (e.g. ``self._message_bus``); otherwise pull
    from the global ``Container``; otherwise return None. The returned value is
    guaranteed to expose a ``publish`` attribute when non-None.
    """
    if fallback is not None and hasattr(fallback, "publish"):
        return fallback
    try:
        from magi.core.container import Container

        bus = Container.message_bus()
    except Exception:
        return None
    if bus is None or type(bus).__name__ == "object":
        return None
    if not hasattr(bus, "publish"):
        return None
    return bus


async def publish_trace_span(
    *,
    event_bus,
    node_type: str,
    name: str,
    span_id: Optional[str] = None,
    trace_id: str,
    parent_span_id: Optional[str] = None,
    status: str = "ok",
    started_at_ms: int,
    ended_at_ms: int,
    error: Optional[ToolError] = None,
    result_preview: Optional[str] = None,
    turn_id: Optional[str] = None,
    attributes: Optional[Mapping[str, Any]] = None,
) -> None:
    """Construct + publish SpanCompleted. Errors are swallowed; trace is best-effort."""
    if event_bus is None:
        logger.debug("publish_trace_span: event_bus is None; skipping (node_type=%s)", node_type)
        return
    payload = SpanCompleted(
        span_id=span_id or str(uuid.uuid4()),
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        node_type=node_type,
        name=name,
        status=status,
        started_at_ms=started_at_ms,
        ended_at_ms=ended_at_ms,
        duration_ms=max(0, ended_at_ms - started_at_ms),
        error=error,
        result_preview=result_preview,
        turn_id=turn_id,
        attributes=dict(attributes or {}),
    )
    try:
        await event_bus.publish(Event(
            type=EventTypes.SPAN_COMPLETED,
            data=payload,
            source="trace_publisher",
        ))
    except Exception:
        logger.exception("publish SpanCompleted failed (span=%s)", payload.span_id)
