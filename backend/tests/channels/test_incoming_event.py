import pytest
from magi_plugin_sdk.run_trigger import IncomingEvent, INCOMING_EVENT_TYPES


def test_incoming_event_constructs_user_steer():
    e = IncomingEvent(
        event_id="e1",
        event_type="user_steer",
        target_run_id="r1",
        arrived_at_ms=1234,
        payload={"content": "wait actually..."},
    )
    assert e.event_id == "e1"
    assert e.event_type == "user_steer"
    assert e.target_run_id == "r1"
    assert e.arrived_at_ms == 1234


def test_incoming_event_is_frozen():
    e = IncomingEvent(
        event_id="e1", event_type="user_steer",
        target_run_id="r1", arrived_at_ms=1,
        payload={},
    )
    with pytest.raises(Exception):
        e.event_id = "e2"


def test_incoming_event_rejects_unknown_event_type():
    with pytest.raises(ValueError, match="event_type"):
        IncomingEvent(
            event_id="e1", event_type="bad_type",
            target_run_id="r1", arrived_at_ms=1,
            payload={},
        )


def test_incoming_event_all_9_event_types_known():
    expected = {
        "user_steer", "user_augment", "user_defer", "user_retract",
        "external_inbound", "scheduled_fire",
        "child_run_completed", "tool_advisory_arrival",
        "sensor_event",
    }
    assert set(INCOMING_EVENT_TYPES) == expected


def test_incoming_event_all_9_event_types_accepted():
    for et in INCOMING_EVENT_TYPES:
        e = IncomingEvent(
            event_id=f"e-{et}", event_type=et,
            target_run_id="r1", arrived_at_ms=1,
            payload={},
        )
        assert e.event_type == et


def test_incoming_event_target_run_id_may_be_none():
    # external_inbound can arrive before any run exists
    e = IncomingEvent(
        event_id="e1", event_type="external_inbound",
        target_run_id=None, arrived_at_ms=42,
        payload={"chat_id": "tg:99"},
    )
    assert e.target_run_id is None


def test_incoming_event_arrived_at_ms_coerced_to_int():
    e = IncomingEvent(
        event_id="e1", event_type="user_steer",
        target_run_id="r1", arrived_at_ms=42,
        payload={},
    )
    d = e.to_dict()
    assert d["arrived_at_ms"] == 42
    assert isinstance(d["arrived_at_ms"], int)

    # from_dict coerces string-ish ms to int
    e2 = IncomingEvent.from_dict({
        "event_id": "e2", "event_type": "user_steer",
        "target_run_id": "r1", "arrived_at_ms": "100",
        "payload": {},
    })
    assert e2.arrived_at_ms == 100
    assert isinstance(e2.arrived_at_ms, int)


def test_incoming_event_to_dict_roundtrip():
    e = IncomingEvent(
        event_id="e1", event_type="child_run_completed",
        target_run_id="r-parent", arrived_at_ms=999,
        payload={"child_run_id": "r-child", "result": "ok"},
    )
    d = e.to_dict()
    e2 = IncomingEvent.from_dict(d)
    assert e2 == e


def test_incoming_event_from_dict_handles_missing_payload():
    e = IncomingEvent.from_dict({
        "event_id": "e1", "event_type": "user_steer",
        "target_run_id": "r1", "arrived_at_ms": 1,
    })
    assert e.payload == {}
