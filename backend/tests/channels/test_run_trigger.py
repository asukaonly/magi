import pytest
from magi_plugin_sdk.run_trigger import RunTrigger


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


def test_run_trigger_to_dict_roundtrip():
    t = RunTrigger(
        trigger_type="external_inbound", source_channel="telegram:42",
        requester="external-user-1", priority="background",
        correlation=["msg-tg-100"], payload={"chat_id": "42"},
    )
    d = t.to_dict()
    t2 = RunTrigger.from_dict(d)
    assert t2 == t
