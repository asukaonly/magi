from __future__ import annotations
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional
from ulid import ULID


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]


_current: contextvars.ContextVar[Optional[TraceContext]] = contextvars.ContextVar(
    "magi_trace_context", default=None,
)


def current_trace_context() -> Optional[TraceContext]:
    return _current.get()


@contextmanager
def start_span(*, trace_id: Optional[str] = None) -> Iterator[TraceContext]:
    parent = _current.get()
    new_ctx = TraceContext(
        trace_id=trace_id or (parent.trace_id if parent else str(ULID())),
        span_id=str(ULID()),
        parent_span_id=parent.span_id if parent else None,
    )
    token = _current.set(new_ctx)
    try:
        yield new_ctx
    finally:
        _current.reset(token)
