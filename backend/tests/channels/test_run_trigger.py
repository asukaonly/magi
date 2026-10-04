import pytest
from magi_plugin_sdk.run_trigger import RunTrigger


@pytest.mark.parametrize(
    "case_invalid_field,case_trigger_type,case_priority",
    [
        pytest.param(
            "trigger_type", "bad_type", "foreground", id="run_trigger_rejects_unknown_trigger_type"
        ),
        pytest.param(
            "priority", "user_message", "not_a_priority", id="run_trigger_rejects_unknown_priority"
        ),
    ],
)
def test_run_trigger_rejects_invalid_enum_values(
    case_invalid_field, case_trigger_type, case_priority
):
    with pytest.raises(ValueError, match=case_invalid_field):
        RunTrigger(
            trigger_type=case_trigger_type,
            source_channel=None,
            requester="u1",
            priority=case_priority,
            correlation=[],
            payload={},
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
