"""BackgroundTaskSpec carries a RunTrigger (ADR-0004 P3, additive)."""
from __future__ import annotations

import pytest

from magi_plugin_sdk.run_trigger import RunTrigger

from magi.agent.background.contracts import BackgroundTaskSpec, BackgroundTaskTriggerSource


@pytest.mark.parametrize("with_trigger", [False, True])
def test_background_spec_roundtrips_typed_and_coarse_trigger_fields(with_trigger):
    trigger = (
        RunTrigger(
            trigger_type="scheduled",
            source_channel="scheduler",
            requester="u1",
            priority="background",
            correlation=["sched-1"],
            payload={"schedule_id": "sched-1"},
        )
        if with_trigger
        else None
    )
    source = (
        BackgroundTaskTriggerSource.SCHEDULE if with_trigger else BackgroundTaskTriggerSource.MANUAL
    )
    spec = BackgroundTaskSpec(
        user_id="u1",
        session_id="s1",
        origin_turn_id="t1",
        title="x",
        goal="g",
        trigger_source=source,
        trigger=trigger,
    )
    restored = BackgroundTaskSpec.from_dict(spec.to_dict())
    assert restored.trigger == trigger
    assert restored.trigger_source is source
    assert restored.to_dict() == spec.to_dict()


@pytest.mark.parametrize(
    "trigger_type,expected",
    [
        # A user request — direct chat or steered/retracted — folds to USER.
        ("user_message", BackgroundTaskTriggerSource.USER),
        ("user_steer", BackgroundTaskTriggerSource.USER),
        ("user_retract", BackgroundTaskTriggerSource.USER),
        # External channel (iMessage/weixin/slack) is still a user; the channel
        # itself lives on trigger.source_channel, not in this coarse enum.
        ("external_inbound", BackgroundTaskTriggerSource.USER),
        ("scheduled", BackgroundTaskTriggerSource.SCHEDULE),
        # A resume of an already-detached run keeps the historical MANUAL bucket.
        ("background_resume", BackgroundTaskTriggerSource.MANUAL),
        # Machine-originated runs have no dedicated bucket → neutral RULE.
        ("source_event", BackgroundTaskTriggerSource.RULE),
        ("agent_self", BackgroundTaskTriggerSource.RULE),
        ("child_run_completed", BackgroundTaskTriggerSource.RULE),
        ("batch", BackgroundTaskTriggerSource.RULE),
    ],
)
def test_from_trigger_maps_trigger_type_to_source(
    trigger_type: str, expected: BackgroundTaskTriggerSource
) -> None:
    trigger = RunTrigger(
        trigger_type=trigger_type,
        source_channel=None,
        requester="u1",
        priority="foreground",
    )
    assert BackgroundTaskTriggerSource.from_trigger(trigger) is expected


def test_from_trigger_unknown_type_degrades_to_rule() -> None:
    # RunTrigger itself rejects unknown types, but from_trigger is duck-typed
    # and must degrade a future/foreign trigger object to RULE, never raise.
    from types import SimpleNamespace

    fake = SimpleNamespace(trigger_type="some_future_type")
    assert BackgroundTaskTriggerSource.from_trigger(fake) is BackgroundTaskTriggerSource.RULE


def test_from_trigger_none_defaults_to_manual() -> None:
    # A run predating trigger propagation (no trigger) keeps the legacy detach
    # default of MANUAL.
    assert BackgroundTaskTriggerSource.from_trigger(None) is BackgroundTaskTriggerSource.MANUAL
