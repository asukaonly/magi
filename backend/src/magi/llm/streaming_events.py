"""Typed LLM streaming events and a contextvar-based sink.

The sink is set at turn entry in ``ChatTaskAgent`` and any layer that
produces LLM output (provider bridge, planner, aggregator, function
calling) emits typed events to it. Python's asyncio copies the current
context into every ``create_task``, so the sink propagates naturally
into spawned subtasks (e.g. parallel worker orchestration).

Events are lightweight dataclasses converted to wire-format dicts by
``to_wire_dict`` when serialised to the realtime channel.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional

StreamEventKind = Literal[
    "text_delta",
    "reasoning_delta",
    "status_update",
    "text_flush",
    "text_reset",
    "tool_call_start",
    "tool_call_args",
    "tool_call_end",
    "usage",
    "error",
    "done",
]


@dataclass(slots=True)
class LLMStreamEvent:
    """A single event in an LLM stream.

    Only the fields relevant to ``kind`` are populated. Unused fields
    stay ``None`` and are omitted from the wire payload.
    """

    kind: StreamEventKind
    text: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args_delta: Optional[str] = None
    tool_arguments: Optional[dict[str, Any]] = None
    usage: Optional[dict[str, int]] = None
    error_kind: Optional[str] = None
    error_message: Optional[str] = None
    source: Optional[str] = None
    step_label: Optional[str] = None

    def to_wire_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        for attr in (
            "text",
            "tool_call_id",
            "tool_name",
            "tool_args_delta",
            "tool_arguments",
            "usage",
            "error_kind",
            "error_message",
            "source",
            "step_label",
        ):
            value = getattr(self, attr)
            if value is not None:
                out[attr] = value
        return out


StreamEventSink = Callable[[LLMStreamEvent], Awaitable[None]]


_STREAM_SINK: ContextVar[Optional[StreamEventSink]] = ContextVar(
    "magi_llm_stream_sink", default=None
)
_STREAM_SOURCE: ContextVar[Optional[str]] = ContextVar(
    "magi_llm_stream_source", default=None
)


def get_stream_sink() -> Optional[StreamEventSink]:
    """Return the sink bound to the current async context, if any."""

    return _STREAM_SINK.get()


def get_stream_source() -> Optional[str]:
    """Return the default ``source`` label for the current context."""

    return _STREAM_SOURCE.get()


_USER_VISIBLE_TEXT_KINDS: frozenset[str] = frozenset(
    {"text_delta", "text_flush", "text_reset", "reasoning_delta"}
)
_USER_VISIBLE_SOURCES: frozenset[str] = frozenset(
    {"chat", "aggregator", "failure_status"}
)


async def emit_stream_event(event: LLMStreamEvent) -> None:
    """Forward ``event`` to the sink bound to the current context.

    Adds the contextual ``source`` label when the event does not already
    carry one. Drops user-visible text events whose source is not one of
    the user-facing final response streams so planner/worker LLM output
    cannot leak into the assistant bubble. Sink failures are swallowed
    since streaming is best-effort: a misbehaving consumer must not
    break the LLM call.
    """

    sink = _STREAM_SINK.get()
    if sink is None:
        return
    if event.source is None:
        source = _STREAM_SOURCE.get()
        if source is not None:
            event.source = source
    if (
        event.kind in _USER_VISIBLE_TEXT_KINDS
        and event.source is not None
        and event.source not in _USER_VISIBLE_SOURCES
    ):
        return
    try:
        await sink(event)
    except Exception:  # noqa: BLE001 - streaming is best-effort
        pass


@asynccontextmanager
async def stream_scope(
    sink: Optional[StreamEventSink],
    *,
    source: Optional[str] = None,
):
    """Install ``sink`` (and optional default ``source``) for the block.

    Using ``None`` as sink disables streaming within the block even if a
    parent scope had one installed.
    """

    sink_token = _STREAM_SINK.set(sink)
    source_token = _STREAM_SOURCE.set(source) if source is not None else None
    try:
        yield
    finally:
        _STREAM_SINK.reset(sink_token)
        if source_token is not None:
            _STREAM_SOURCE.reset(source_token)


@asynccontextmanager
async def stream_source(source: str):
    """Override only the ``source`` label for nested emits."""

    token = _STREAM_SOURCE.set(source)
    try:
        yield
    finally:
        _STREAM_SOURCE.reset(token)
