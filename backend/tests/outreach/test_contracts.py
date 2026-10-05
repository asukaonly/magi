import pytest

from magi.outreach.contracts import (
    OutreachIntent, OutreachKind, Urgency,
)


def _intent() -> OutreachIntent:
    return OutreachIntent(
        kind=OutreachKind.TASK_COMPLETED,
        user_id="u1",
        origin_session_id="s1",
        title="Find flights",
        facts="Found 3 options under $400.",
        correlation_id="task_abc",
        completed_at_ms=1_700_000_000_000,
        origin_turn_id="turn-1",
        pending_message_id="msg_pending",
        urgency=Urgency.HIGH,
        payload={"background_task_id": "task_abc"},
    )


@pytest.mark.parametrize("with_optionals", [False, True])
def test_intent_wire_roundtrip(with_optionals):
    intent = (
        _intent()
        if with_optionals
        else OutreachIntent(
            kind=OutreachKind.TASK_FAILED,
            user_id="u1",
            origin_session_id=None,
            title="t",
            facts="boom",
            correlation_id="c2",
            completed_at_ms=1_700_000_000_000,
        )
    )
    restored = OutreachIntent.from_dict(intent.to_dict())
    assert restored == intent
    assert restored.kind is (
        OutreachKind.TASK_COMPLETED if with_optionals else OutreachKind.TASK_FAILED
    )
    assert restored.urgency is (Urgency.HIGH if with_optionals else Urgency.NORMAL)
    assert restored.origin_session_id == ("s1" if with_optionals else None)
    assert restored.origin_turn_id == ("turn-1" if with_optionals else None)
    assert restored.pending_message_id == ("msg_pending" if with_optionals else None)
    assert restored.payload == ({"background_task_id": "task_abc"} if with_optionals else {})
