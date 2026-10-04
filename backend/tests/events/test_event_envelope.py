from __future__ import annotations

import json
from contextlib import nullcontext

import pytest

from magi.events.events import Event, EventLevel
from magi.events.tracing import TraceContext, start_span


@pytest.mark.parametrize(
    "envelope",
    [{}, {"event_id": None, "correlation_id": None, "causation_id": None, "trace_context": None}],
)
def test_generated_event_identity_is_unique_and_stable_across_json_roundtrip(envelope):
    events = [Event.from_dict({"type": "X", "data": {"k": "v"}, **envelope}) for _ in range(8)]
    ids = [event.event_id for event in events]
    assert all(isinstance(event_id, str) and event_id for event_id in ids)
    assert len(set(ids)) == len(events)
    for event in events:
        wire = json.loads(json.dumps(event.to_dict()))
        restored = Event.from_dict(wire)
        assert restored.to_dict() == wire
        assert restored.event_id == restored.correlation_id == event.event_id
        assert restored.causation_id is None
        assert restored.trace_context is None


@pytest.mark.parametrize("trace_source", ["outside", "ambient", "explicit"])
def test_envelope_json_preserves_correlation_causation_and_selected_trace(trace_source):
    explicit = TraceContext(
        trace_id="explicit-trace", span_id="explicit-span", parent_span_id="parent"
    )
    with start_span() if trace_source != "outside" else nullcontext() as ambient:
        event = Event(
            type="X",
            data={"k": "v"},
            timestamp=1700000000.0,
            source="test-source",
            level=EventLevel.WARNING,
            event_id="evt-1",
            correlation_id="corr-1",
            causation_id="caus-1",
            trace_context=explicit if trace_source == "explicit" else None,
            metadata={"attempt": 2},
        )
    expected_trace = explicit if trace_source == "explicit" else ambient
    assert event.trace_context is expected_trace
    wire = json.loads(json.dumps(event.to_dict()))
    assert wire == {
        "type": "X",
        "data": {"k": "v"},
        "timestamp": 1700000000.0,
        "source": "test-source",
        "level": 2,
        "event_id": "evt-1",
        "correlation_id": "corr-1",
        "causation_id": "caus-1",
        "metadata": {"attempt": 2},
        "trace_context": None
        if expected_trace is None
        else {
            "trace_id": expected_trace.trace_id,
            "span_id": expected_trace.span_id,
            "parent_span_id": expected_trace.parent_span_id,
        },
    }
    restored = Event.from_dict(wire)
    assert restored.to_dict() == wire
