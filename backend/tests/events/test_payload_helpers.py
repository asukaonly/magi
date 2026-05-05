from __future__ import annotations
import pytest
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import ToolInvocationCompleted, TaskContext
from magi.events.payload_helpers import expect_payload, PayloadTypeError


def _sample_event() -> Event:
    return Event(
        type=EventTypes.TOOL_INVOCATION_COMPLETED,
        data=ToolInvocationCompleted(
            tool_name="x", tool_category="internal",
            success=True, duration_ms=1.0,
            started_at=1.0, finished_at=2.0,
            args_summary=None, result_summary=None, error=None,
            context=TaskContext(None, None, None, None),
        ),
    )


def test_expect_payload_returns_typed_payload():
    event = _sample_event()
    payload = expect_payload(event, ToolInvocationCompleted)
    assert payload.tool_name == "x"


def test_expect_payload_raises_on_wrong_type():
    event = Event(type="Foo", data={"not": "a dataclass"})
    with pytest.raises(PayloadTypeError):
        expect_payload(event, ToolInvocationCompleted)


def test_expect_payload_raises_when_data_is_none():
    event = Event(type="Foo", data=None)
    with pytest.raises(PayloadTypeError):
        expect_payload(event, ToolInvocationCompleted)
