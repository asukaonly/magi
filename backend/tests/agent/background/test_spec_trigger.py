"""BackgroundTaskSpec carries a RunTrigger (ADR-0004 P3, additive)."""
from __future__ import annotations

from magi_plugin_sdk.run_trigger import RunRequest, RunTrigger

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


def test_as_run_request_projects_spec() -> None:
    """ADR-0004 P3: a BackgroundTaskSpec projects into a unified RunRequest
    (what to run / for whom), leaving the background-specific how on the spec."""
    trigger = RunTrigger(
        trigger_type="scheduled",
        source_channel="scheduler",
        requester="u1",
        priority="background",
    )
    spec = BackgroundTaskSpec(
        user_id="u1",
        session_id="s1",
        origin_turn_id="t1",
        title="x",
        goal="do the thing",
        trigger=trigger,
        max_iterations=7,
        timeout_seconds=900,
    )
    req = spec.as_run_request()
    assert req.trigger is trigger
    assert req.session_id == "s1"
    assert req.input == {"goal": "do the thing"}
    assert req.bounds == {"max_iterations": 7, "timeout_seconds": 900}


def test_as_run_request_falls_back_to_background_resume_trigger() -> None:
    """A spec with no trigger (predating propagation) still projects to a valid
    RunRequest, synthesizing a background_resume trigger."""
    spec = BackgroundTaskSpec(
        user_id="u9", session_id="s9", origin_turn_id="t9", title="x", goal="g"
    )
    req = spec.as_run_request()
    assert isinstance(req, RunRequest)
    assert req.trigger.trigger_type == "background_resume"
    assert req.trigger.requester == "u9"
