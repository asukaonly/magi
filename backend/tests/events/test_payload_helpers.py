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


@pytest.mark.parametrize("kind", ["typed", "mapping", "none"])
def test_payload_guard_preserves_typed_identity_and_rejects_untyped_values(kind):
    event = _sample_event()
    if kind == "typed":
        assert expect_payload(event, ToolInvocationCompleted) is event.data
    else:
        event.data = {"not": "a dataclass"} if kind == "mapping" else None
        with pytest.raises(PayloadTypeError):
            expect_payload(event, ToolInvocationCompleted)
