"""BackgroundTaskSpec carries a RunTrigger (ADR-0004 P3, additive)."""
from __future__ import annotations

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
