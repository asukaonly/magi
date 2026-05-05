from __future__ import annotations
import pytest
from magi.events.events import Event
from magi.events.tracing import TraceContext, start_span
from magi.memory.event_contracts import normalize_runtime_event, MemoryEvent


def _basic_event(**kw):
    return Event(
        type="UserMessage",
        data={"content": "hi", "session_id": "s", "user_id": "u"},
        source="chat",
        **kw,
    )


def test_envelope_event_id_preserved_through_normalize():
    e = _basic_event(event_id="ulid-from-producer")
    me = normalize_runtime_event(e)
    assert me.event_id == "ulid-from-producer"


def test_envelope_event_id_takes_priority_over_kwarg():
    e = _basic_event(event_id="ulid-from-producer")
    me = normalize_runtime_event(e, event_id="kwarg-id")
    # spec §6.2: envelope wins over kwarg
    assert me.event_id == "ulid-from-producer"


def test_kwarg_used_only_when_envelope_missing():
    e = _basic_event()
    e.event_id = None  # legacy path simulation
    me = normalize_runtime_event(e, event_id="kwarg-id")
    assert me.event_id == "kwarg-id"


def test_causation_id_mirrored():
    e = _basic_event(causation_id="parent-evt-1")
    me = normalize_runtime_event(e)
    assert me.causation_id == "parent-evt-1"


def test_causation_kwarg_fallback():
    e = _basic_event()
    me = normalize_runtime_event(e, parent_event_id="legacy-parent")
    assert me.causation_id == "legacy-parent"


def test_trace_context_split_into_three_columns():
    tc = TraceContext(trace_id="trace-x", span_id="span-y", parent_span_id="parent-z")
    e = _basic_event(trace_context=tc)
    me = normalize_runtime_event(e)
    assert me.trace_id == "trace-x"
    assert me.span_id == "span-y"
    assert me.parent_span_id == "parent-z"


def test_no_trace_context_yields_none_columns():
    e = _basic_event()
    me = normalize_runtime_event(e)
    assert me.trace_id is None
    assert me.span_id is None
    assert me.parent_span_id is None


def test_inside_span_event_normalize_picks_up_trace_columns():
    with start_span() as ctx:
        e = _basic_event()
    me = normalize_runtime_event(e)
    assert me.trace_id == ctx.trace_id
    assert me.span_id == ctx.span_id
    assert me.parent_span_id == ctx.parent_span_id
