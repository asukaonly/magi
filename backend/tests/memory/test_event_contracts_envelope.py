from __future__ import annotations
import pytest
from magi.events.events import Event
from magi.events.tracing import TraceContext, start_span
from magi.memory.event_contracts import normalize_runtime_event


def _basic_event(**kw):
    return Event(
        type="UserMessage",
        data={"content": "hi", "session_id": "s", "user_id": "u"},
        source="chat",
        **kw,
    )


@pytest.mark.parametrize(
    ("producer_id", "fallback", "expected"),
    [
        ("producer", None, "producer"),
        ("producer", "fallback", "producer"),
        (None, "fallback", "fallback"),
    ],
)
def test_normalization_preserves_producer_identity_before_explicit_fallback(
    producer_id, fallback, expected
):
    event = _basic_event()
    event.event_id = producer_id
    assert normalize_runtime_event(event, event_id=fallback).event_id == expected


def test_causation_kwarg_fallback():
    e = _basic_event()
    me = normalize_runtime_event(e, parent_event_id="legacy-parent")
    assert me.causation_id == "legacy-parent"


@pytest.mark.parametrize("has_trace", [False, True])
def test_normalized_envelope_preserves_causation_and_optional_trace(has_trace):
    trace = (
        TraceContext(trace_id="trace-x", span_id="span-y", parent_span_id="parent-z")
        if has_trace
        else None
    )
    event = _basic_event(causation_id="parent-event", trace_context=trace)
    result = normalize_runtime_event(event, parent_event_id="fallback-parent")
    assert result.causation_id == "parent-event"
    assert (result.trace_id, result.span_id, result.parent_span_id) == (
        ("trace-x", "span-y", "parent-z") if has_trace else (None, None, None)
    )


def test_inside_span_event_normalize_picks_up_trace_columns():
    with start_span() as ctx:
        e = _basic_event()
    me = normalize_runtime_event(e)
    assert me.trace_id == ctx.trace_id
    assert me.span_id == ctx.span_id
    assert me.parent_span_id == ctx.parent_span_id
