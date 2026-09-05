import pytest
from magi_plugin_sdk.run_trigger import RunTrigger, RUN_TRIGGER_TYPES


def test_run_trigger_constructs_user_message():
    t = RunTrigger(
        trigger_type="user_message",
        source_channel=None,
        requester="u1",
        priority="foreground",
        correlation=["fact-1"],
        payload={"content": "hi"},
    )
    assert t.trigger_type == "user_message"
    assert t.priority == "foreground"


def test_run_trigger_is_frozen():
    t = RunTrigger(
        trigger_type="user_message", source_channel=None,
        requester="u1", priority="foreground",
        correlation=[], payload={},
    )
    with pytest.raises(Exception):
        t.requester = "u2"


def test_run_trigger_rejects_unknown_trigger_type():
    with pytest.raises(ValueError, match="trigger_type"):
        RunTrigger(
            trigger_type="bad_type", source_channel=None,
            requester="u1", priority="foreground",
            correlation=[], payload={},
        )


def test_run_trigger_rejects_unknown_priority():
    with pytest.raises(ValueError, match="priority"):
        RunTrigger(
            trigger_type="user_message", source_channel=None,
            requester="u1", priority="not_a_priority",
            correlation=[], payload={},
        )


def test_run_trigger_all_trigger_types_known():
    expected = {
        "user_message", "user_steer", "user_retract", "scheduled",
        "external_inbound", "source_event", "agent_self",
        "child_run_completed", "background_resume",
        # ADR-0004 P3: batch runs carry their own trigger type.
        "batch",
    }
    assert set(RUN_TRIGGER_TYPES) == expected


def test_run_trigger_to_dict_roundtrip():
    t = RunTrigger(
        trigger_type="external_inbound", source_channel="telegram:42",
        requester="external-user-1", priority="background",
        correlation=["msg-tg-100"], payload={"chat_id": "42"},
    )
    d = t.to_dict()
    t2 = RunTrigger.from_dict(d)
    assert t2 == t
