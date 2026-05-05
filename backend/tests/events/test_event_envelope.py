from __future__ import annotations
import pytest
from magi.events.events import Event, EventLevel
from magi.events.tracing import TraceContext, start_span


def test_default_event_id_is_nonempty_string():
    e = Event(type="X", data=None)
    assert isinstance(e.event_id, str)
    assert len(e.event_id) > 0


def test_explicit_event_id_preserved():
    e = Event(type="X", data=None, event_id="my-id")
    assert e.event_id == "my-id"


def test_correlation_defaults_to_event_id():
    e = Event(type="X", data=None)
    assert e.correlation_id == e.event_id


def test_explicit_correlation_id_preserved():
    e = Event(type="X", data=None, correlation_id="corr-1")
    assert e.correlation_id == "corr-1"
    assert e.event_id != "corr-1"


def test_causation_id_default_none():
    e = Event(type="X", data=None)
    assert e.causation_id is None


def test_explicit_causation_id_preserved():
    e = Event(type="X", data=None, causation_id="parent-evt")
    assert e.causation_id == "parent-evt"


def test_trace_context_default_none_outside_span():
    e = Event(type="X", data=None)
    assert e.trace_context is None


def test_trace_context_picked_up_inside_span():
    with start_span() as ctx:
        e = Event(type="X", data=None)
    assert e.trace_context is ctx


def test_explicit_trace_context_preserved_inside_span():
    explicit = TraceContext(trace_id="t", span_id="s", parent_span_id=None)
    with start_span():
        e = Event(type="X", data=None, trace_context=explicit)
    assert e.trace_context is explicit


def test_to_dict_round_trip_with_envelope_fields():
    explicit_tc = TraceContext(trace_id="t", span_id="s", parent_span_id="p")
    e = Event(
        type="X", data={"k": "v"},
        event_id="evt-1", correlation_id="corr-1",
        causation_id="caus-1", trace_context=explicit_tc,
    )
    d = e.to_dict()
    assert d["event_id"] == "evt-1"
    assert d["correlation_id"] == "corr-1"
    assert d["causation_id"] == "caus-1"
    assert d["trace_context"] == {
        "trace_id": "t", "span_id": "s", "parent_span_id": "p",
    }
    e2 = Event.from_dict(d)
    assert e2.event_id == "evt-1"
    assert e2.correlation_id == "corr-1"
    assert e2.causation_id == "caus-1"
    assert e2.trace_context == explicit_tc


def test_from_dict_missing_new_fields_fills_none():
    e = Event.from_dict({"type": "X", "data": None})
    assert e.event_id is not None  # auto-filled by __post_init__
    assert e.causation_id is None
    assert e.trace_context is None


def test_from_dict_with_null_trace_context():
    e = Event.from_dict({"type": "X", "data": None, "trace_context": None})
    assert e.trace_context is None
