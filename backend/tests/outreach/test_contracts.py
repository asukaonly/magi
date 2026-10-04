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


def test_intent_roundtrips_through_dict():
    intent = _intent()
    restored = OutreachIntent.from_dict(intent.to_dict())
    assert restored == intent
    assert restored.kind is OutreachKind.TASK_COMPLETED
    assert restored.urgency is Urgency.HIGH
    assert restored.origin_turn_id == "turn-1"
    assert restored.payload == {"background_task_id": "task_abc"}


def test_intent_roundtrips_with_none_optionals():
    # The common "completed task with no session linkage" shape: exercises the
    # data.get(...) -> None -> stored-as-None path and the NORMAL/empty defaults.
    intent = OutreachIntent(
        kind=OutreachKind.TASK_FAILED,
        user_id="u1",
        origin_session_id=None,
        title="t",
        facts="boom",
        correlation_id="c2",
        completed_at_ms=1_700_000_000_000,
    )
    restored = OutreachIntent.from_dict(intent.to_dict())
    assert restored == intent
    assert restored.origin_session_id is None
    assert restored.origin_turn_id is None
    assert restored.pending_message_id is None
    assert restored.urgency is Urgency.NORMAL
    assert restored.payload == {}
