"""Contextvars-driven trace span tracking for the event envelope.

Producers wrap business code:

    with start_span(node_type="tool_invocation", name=tool_name) as span:
        span.set_attribute("tool_name", tool_name)
        ...

On with-exit, a SpanCompleted event is published fire-and-forget to the
configured EventBus (resolved from magi.core.container.Container.message_bus).
RuntimeTraceSubscriber consumes these events and projects them into 5
runtime_trace tables.

For async business code use start_async_span. For critical spans where the
caller must observe publish completion before returning, pass delivery="sync"
on the async variant; it will await the publish.

Event.__post_init__ also reads current_trace_context() to fill the envelope
trace_context field for events constructed inside a span.

Span subclasses TraceContext so that A-era code that treats the yielded
object as a TraceContext (isinstance / .trace_id / .span_id /
.parent_span_id) keeps working unchanged.
"""
from __future__ import annotations
import asyncio
import contextvars
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator, Mapping, Optional

from ulid import ULID

from .domain_payloads import SpanCompleted, ToolError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]


class Span(TraceContext):
    def __init__(
        self,
        *,
        node_type: str,
        name: str,
        context: TraceContext,
        started_at_ms: int,
    ) -> None:
        object.__setattr__(self, "trace_id", context.trace_id)
        object.__setattr__(self, "span_id", context.span_id)
        object.__setattr__(self, "parent_span_id", context.parent_span_id)
        object.__setattr__(self, "_node_type", node_type)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_started_at_ms", started_at_ms)
        object.__setattr__(self, "_attributes", {})
        object.__setattr__(self, "_status", "ok")
        object.__setattr__(self, "_error", None)
        object.__setattr__(self, "_result_preview", None)
        object.__setattr__(self, "_turn_id", None)

    def __setattr__(self, key: str, value: Any) -> None:
        object.__setattr__(self, key, value)

    @property
    def context(self) -> "Span":
        return self

    @property
    def node_type(self) -> str:
        return self._node_type

    def set_name(self, name: str) -> None:
        self._name = name

    def set_attribute(self, key: str, value: Any) -> None:
        self._attributes[key] = value

    def set_attributes(self, attrs: Mapping[str, Any]) -> None:
        self._attributes.update(attrs)

    def set_status(self, status: str) -> None:
        self._status = status

    def record_exception(self, exc: BaseException) -> None:
        self._status = "error"
        message = str(exc)[:1000]
        self._error = ToolError(type=type(exc).__name__, message=message)

    def set_result_preview(self, preview: Optional[str]) -> None:
        self._result_preview = preview

    def set_turn_id(self, turn_id: Optional[str]) -> None:
        self._turn_id = turn_id

    def _to_completed_payload(self, ended_at_ms: int) -> SpanCompleted:
        return SpanCompleted(
            span_id=self.span_id,
            trace_id=self.trace_id,
            parent_span_id=self.parent_span_id,
            node_type=self._node_type,
            name=self._name,
            status=self._status,
            started_at_ms=self._started_at_ms,
            ended_at_ms=ended_at_ms,
            duration_ms=ended_at_ms - self._started_at_ms,
            error=self._error,
            result_preview=self._result_preview,
            turn_id=self._turn_id,
            attributes=dict(self._attributes),
        )


_current_trace_context: contextvars.ContextVar[Optional[TraceContext]] = contextvars.ContextVar(
    "magi_trace_context", default=None,
)
_current_span: contextvars.ContextVar[Optional[Span]] = contextvars.ContextVar(
    "magi_current_span", default=None,
)


def current_trace_context() -> Optional[TraceContext]:
    return _current_trace_context.get()


def current_span() -> Optional[Span]:
    return _current_span.get()


_PENDING: set[asyncio.Task] = set()


def _track_pending(task: asyncio.Task) -> None:
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


async def drain_pending() -> None:
    if not _PENDING:
        return
    await asyncio.gather(*list(_PENDING), return_exceptions=True)


def _resolve_event_bus() -> Any:
    try:
        from ..core.container import get_container

        bus = get_container().message_bus()
    except Exception:
        return None
    if bus is None or not hasattr(bus, "publish"):
        return None
    return bus


def _new_context(trace_id: Optional[str], parent_ctx: Optional[TraceContext]) -> TraceContext:
    return TraceContext(
        trace_id=trace_id or (parent_ctx.trace_id if parent_ctx else str(ULID())),
        span_id=str(ULID()),
        parent_span_id=parent_ctx.span_id if parent_ctx else None,
    )


def _build_span(
    *,
    node_type: str,
    name: str,
    trace_id: Optional[str],
) -> Span:
    parent_ctx = _current_trace_context.get()
    ctx = _new_context(trace_id, parent_ctx)
    started_at_ms = int(time.time() * 1000)
    span = Span(node_type=node_type, name=name, context=ctx, started_at_ms=started_at_ms)
    parent_span = _current_span.get()
    if parent_span is not None and parent_span._turn_id is not None:
        span._turn_id = parent_span._turn_id
    return span


@contextmanager
def start_span(
    *,
    node_type: str = "span",
    name: str = "",
    trace_id: Optional[str] = None,
    delivery: str = "async",
) -> Iterator[Span]:
    span = _build_span(node_type=node_type, name=name, trace_id=trace_id)
    span_token = _current_span.set(span)
    ctx_token = _current_trace_context.set(span)
    try:
        yield span
    except asyncio.CancelledError:
        span.set_status("cancelled")
        raise
    except BaseException as exc:
        span.record_exception(exc)
        raise
    finally:
        _current_span.reset(span_token)
        _current_trace_context.reset(ctx_token)
        ended_at_ms = int(time.time() * 1000)
        try:
            _publish_span_completed_sync(span, ended_at_ms, delivery=delivery)
        except Exception:
            logger.exception("publish SpanCompleted failed (span=%s)", span.span_id)


@asynccontextmanager
async def start_async_span(
    *,
    node_type: str = "span",
    name: str = "",
    trace_id: Optional[str] = None,
    delivery: str = "async",
) -> AsyncIterator[Span]:
    span = _build_span(node_type=node_type, name=name, trace_id=trace_id)
    span_token = _current_span.set(span)
    ctx_token = _current_trace_context.set(span)
    try:
        yield span
    except asyncio.CancelledError:
        span.set_status("cancelled")
        raise
    except BaseException as exc:
        span.record_exception(exc)
        raise
    finally:
        _current_span.reset(span_token)
        _current_trace_context.reset(ctx_token)
        ended_at_ms = int(time.time() * 1000)
        try:
            await _publish_span_completed_async(span, ended_at_ms, delivery=delivery)
        except Exception:
            logger.exception("publish SpanCompleted failed (span=%s)", span.span_id)


def _publish_span_completed_sync(span: Span, ended_at_ms: int, *, delivery: str) -> None:
    payload = span._to_completed_payload(ended_at_ms)
    bus = _resolve_event_bus()
    if bus is None:
        return
    from .events import Event, EventTypes
    event = Event(type=EventTypes.SPAN_COMPLETED, data=payload, source="tracing")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if delivery == "sync":
        logger.debug("delivery=sync requested in sync start_span; degrading to async")
    task = loop.create_task(bus.publish(event))
    _track_pending(task)


async def _publish_span_completed_async(span: Span, ended_at_ms: int, *, delivery: str) -> None:
    payload = span._to_completed_payload(ended_at_ms)
    bus = _resolve_event_bus()
    if bus is None:
        return
    from .events import Event, EventTypes
    event = Event(type=EventTypes.SPAN_COMPLETED, data=payload, source="tracing")
    if delivery == "sync":
        try:
            await bus.publish(event)
        except Exception:
            logger.exception("sync publish failed")
        return
    loop = asyncio.get_running_loop()
    task = loop.create_task(bus.publish(event))
    _track_pending(task)
