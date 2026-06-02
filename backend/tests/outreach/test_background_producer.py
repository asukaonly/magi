import pytest
from magi.agent.background import (
    BackgroundTask, BackgroundTaskSpec, BackgroundTaskStatus, BackgroundTaskTriggerSource,
)
from magi.outreach.contracts import OutreachKind, Urgency
from magi.outreach.producers.background_completion import (
    build_background_completion_producer, task_to_intent,
)


def _task(status, *, trigger=BackgroundTaskTriggerSource.USER, summary="done", error=""):
    spec = BackgroundTaskSpec(user_id="u1", session_id="s1", origin_turn_id="t1",
                              title="Find flights", goal="g", selected_tools=[],
                              trigger_source=trigger)
    task = BackgroundTask.new(spec)
    task.status = status
    task.summary = summary
    task.error = error
    task.finished_at = 1_700_000.0
    return task


def test_succeeded_maps_to_completed_high_urgency():
    intent = task_to_intent(_task(BackgroundTaskStatus.SUCCEEDED))
    assert intent.kind is OutreachKind.TASK_COMPLETED
    assert intent.facts == "done"
    assert intent.urgency is Urgency.HIGH          # USER trigger
    assert intent.completed_at_ms == 1_700_000_000
    assert intent.payload["background_task_status"] == "succeeded"


def test_failed_maps_to_failed():
    intent = task_to_intent(_task(BackgroundTaskStatus.FAILED, summary="", error="boom"))
    assert intent.kind is OutreachKind.TASK_FAILED and intent.facts == "boom"


def test_rule_trigger_is_normal_urgency():
    intent = task_to_intent(_task(BackgroundTaskStatus.SUCCEEDED, trigger=BackgroundTaskTriggerSource.RULE))
    assert intent.urgency is Urgency.NORMAL


def test_missing_session_returns_none():
    spec = BackgroundTaskSpec(user_id="", session_id="", origin_turn_id="t", title="x", goal="g")
    task = BackgroundTask.new(spec); task.status = BackgroundTaskStatus.SUCCEEDED
    assert task_to_intent(task) is None


@pytest.mark.asyncio
async def test_producer_submits_intent():
    submitted = []

    class _Svc:
        async def submit(self, intent): submitted.append(intent)

    producer = build_background_completion_producer(_Svc())
    await producer(_task(BackgroundTaskStatus.SUCCEEDED))
    assert len(submitted) == 1 and submitted[0].correlation_id
