"""Multi-client writes must own both durable definitions and live jobs."""

from dataclasses import replace

import pytest

from magi.scheduler import SchedulerService, ScheduleDefinition, ScheduledTargetType, TriggerDefinition, TriggerType
from magi.scheduler.contracts import ScheduleConflictError
from magi.scheduler.repository import ScheduleRepository


@pytest.mark.asyncio
async def test_conditional_mutations_update_live_jobs_and_preserve_paused_definitions(tmp_path):
    service = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    await service.start(paused=True)
    definition = ScheduleDefinition("client-created", ScheduledTargetType.USER_AGENT_TASK, "client-created", TriggerDefinition(TriggerType.INTERVAL, {"seconds": 3600}))
    try:
        first = await service.schedule(definition, create_only=True)
        assert first.revision > 0
        initial_job = service._scheduler.get_job(first.schedule_id)
        assert initial_job is not None
        repeated = await service.schedule(definition, create_only=True)
        assert repeated.revision == first.revision

        paused = await service.schedule(replace(first, enabled=False), expected_revision=first.revision)
        assert paused.revision > first.revision
        assert await service.get_schedule(first.schedule_id) is not None
        assert service._scheduler.get_job(first.schedule_id) is None
        with pytest.raises(ScheduleConflictError):
            await service.schedule(replace(first, metadata={"title": "old draft"}), expected_revision=first.revision)
        with pytest.raises(ScheduleConflictError):
            await service.unschedule(first.schedule_id, expected_revision=first.revision)

        resumed = await service.schedule(replace(paused, enabled=True), expected_revision=paused.revision)
        old_next = service._scheduler.get_job(first.schedule_id).next_run_time
        changed = await service.schedule(replace(resumed, trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": 30})), expected_revision=resumed.revision)
        assert service._scheduler.get_job(first.schedule_id).next_run_time < old_next
        assert (await service.get_schedule(first.schedule_id)).revision == changed.revision
        await service.unschedule(first.schedule_id, expected_revision=changed.revision)
        assert service._scheduler.get_job(first.schedule_id) is None
        assert await service.get_schedule(first.schedule_id) is None
        # A delayed retry cannot resurrect an executed or deleted schedule.
        with pytest.raises(ScheduleConflictError):
            await service.schedule(definition, create_only=True)
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_independent_repository_writers_cannot_overwrite_a_newer_definition(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    other = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    definition = ScheduleDefinition("shared", ScheduledTargetType.USER_AGENT_TASK, "shared", TriggerDefinition(TriggerType.INTERVAL, {"seconds": 60}))
    await repository.upsert_schedule(definition)
    original = await repository.get_schedule("shared")
    await other.upsert_schedule(replace(original, enabled=False), expected_revision=original.revision)
    with pytest.raises(ScheduleConflictError):
        await repository.upsert_schedule(replace(original, target_payload={"prompt": "stale"}), expected_revision=original.revision)
    with pytest.raises(ScheduleConflictError):
        await repository.delete_schedule("shared", expected_revision=original.revision)
    confirmed = await repository.get_schedule("shared")
    assert confirmed.enabled is False and confirmed.target_payload == {}
    await other.update_schedule_binding("shared", job_id="new-runtime-binding")
    assert (await repository.get_schedule("shared")).revision == confirmed.revision
