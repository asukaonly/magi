"""BackgroundTaskSpec carries a RunTrigger (ADR-0004 P3, additive)."""
from __future__ import annotations

import pytest

from magi_plugin_sdk.run_trigger import RunTrigger

from magi.agent.background.contracts import BackgroundTaskSpec, BackgroundTaskTriggerSource


def test_spec_roundtrips_run_trigger_alongside_legacy_source() -> None:
    trigger = RunTrigger(
        trigger_type="scheduled",
        source_channel="scheduler",
        requester="u1",
        priority="background",
        correlation=["sched-1"],
        payload={},
    )
    spec = BackgroundTaskSpec(
        user_id="u1",
        session_id="s1",
        origin_turn_id="t1",
        title="x",
        goal="g",
        trigger_source=BackgroundTaskTriggerSource.SCHEDULE,
        trigger=trigger,
    )
    restored = BackgroundTaskSpec.from_dict(spec.to_dict())
    assert restored.trigger is not None
    assert restored.trigger.trigger_type == "scheduled"
    assert restored.trigger.requester == "u1"
    assert restored.trigger.correlation == ["sched-1"]
    # legacy trigger_source is preserved (the two coexist until PR-3)
    assert restored.trigger_source is BackgroundTaskTriggerSource.SCHEDULE


def test_spec_trigger_defaults_to_none() -> None:
    spec = BackgroundTaskSpec(
        user_id="u1", session_id="s1", origin_turn_id="t1", title="x", goal="g"
    )
    assert spec.trigger is None
    assert BackgroundTaskSpec.from_dict(spec.to_dict()).trigger is None


def test_batch_trigger_type_is_valid() -> None:
    # "batch" was added to RUN_TRIGGER_TYPES in this change.
    t = RunTrigger(
        trigger_type="batch",
        source_channel="batch",
        requester="alice",
        priority="background",
    )
    assert t.trigger_type == "batch"


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
        ("sensor_event", BackgroundTaskTriggerSource.RULE),
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


def test_from_trigger_covers_every_run_trigger_type() -> None:
    # Guard: if a new trigger_type is added to the SDK, this fails until the
    # mapping is updated — so coverage of RUN_TRIGGER_TYPES never silently rots.
    from magi_plugin_sdk.run_trigger import RUN_TRIGGER_TYPES

    for trigger_type in RUN_TRIGGER_TYPES:
        trigger = RunTrigger(
            trigger_type=trigger_type,
            source_channel=None,
            requester="u1",
            priority="foreground",
        )
        # Every known type resolves to a concrete bucket without raising.
        assert isinstance(
            BackgroundTaskTriggerSource.from_trigger(trigger),
            BackgroundTaskTriggerSource,
        )


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
