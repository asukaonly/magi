import pytest
from magi.outreach.contracts import (
    OutreachIntent, OutreachKind, Urgency, ResolvedTargets, GovernorVerdict,
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
    assert restored.payload == {"background_task_id": "task_abc"}


def test_governor_verdict_members():
    assert {v.name for v in GovernorVerdict} == {"PUSH_NOW", "DEFER", "DROP"}


def test_resolved_targets_defaults_to_none():
    rt = ResolvedTargets()
    assert rt.desktop_session_id is None
    assert rt.external is None
