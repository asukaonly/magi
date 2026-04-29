from __future__ import annotations

import asyncio
import tempfile
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import schedules as schedules_module
from magi.api.routers.schedules import schedules_router
from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.repository import ScheduleRepository


def _build_client(monkeypatch):
    app = FastAPI()
    app.include_router(schedules_router, prefix="/api/schedules")
    runtime_base_dir = tempfile.mkdtemp(prefix="magi-schedules-")
    scheduler_db_path = f"{runtime_base_dir}/runtime/scheduler.db"
    monkeypatch.setattr(
        schedules_module,
        "get_runtime_paths",
        lambda: type(
            "Paths",
            (),
            {
                "base_dir": runtime_base_dir,
                "scheduler_db_path": scheduler_db_path,
            },
        )(),
    )
    repository = ScheduleRepository(scheduler_db_path)
    return TestClient(app), repository


async def _seed_sensor_schedule(repository: ScheduleRepository) -> ScheduleDefinition:
    await repository.initialize()
    schedule = ScheduleDefinition(
        schedule_id="sensor-sync:screen-time:screen_time",
        target_type=ScheduledTargetType.SENSOR_SYNC,
        target_key="screen-time:screen_time",
        trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": 300}),
        target_payload={"plugin_id": "screen-time", "source_type": "screen_time"},
        metadata={"plugin_id": "screen-time", "source_type": "screen_time"},
        job_id="sensor-sync:screen-time:screen_time",
    )
    await repository.upsert_schedule(schedule)
    await repository.update_schedule_binding(
        schedule.schedule_id,
        job_id=schedule.job_id,
        next_run_at=1710000500.0,
    )
    return schedule


async def _seed_agent_schedule(repository: ScheduleRepository) -> ScheduleDefinition:
    await repository.initialize()
    schedule = ScheduleDefinition(
        schedule_id="agent-task:drink-water",
        target_type=ScheduledTargetType.USER_AGENT_TASK,
        target_key="agent-task:drink-water",
        trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": 600}),
        target_payload={
            "kind": "agent_task",
            "title": "Drink water reminder",
            "prompt": "提醒我喝水",
        },
        metadata={
            "display_name": "Drink water reminder",
            "target_kind": "agent_task",
        },
        job_id="agent-task:drink-water",
    )
    await repository.upsert_schedule(schedule)
    return schedule


class _FakeSchedulerService:
    def __init__(self, result: ScheduledExecutionResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bool]] = []

    async def execute_schedule(
        self,
        schedule_id: str,
        *,
        manual: bool = False,
    ) -> ScheduledExecutionResult:
        self.calls.append((schedule_id, manual))
        return self.result


def test_list_schedules_includes_target_state_and_sensor_policy(monkeypatch):
    client, repository = _build_client(monkeypatch)
    asyncio.run(_seed_sensor_schedule(repository))

    response = client.get("/api/schedules", params={"enabled_only": True})

    assert response.status_code == 200
    body = response.json()
    assert body["schedules"][0]["schedule_id"] == "sensor-sync:screen-time:screen_time"
    assert body["schedules"][0]["editable"] is False
    assert body["schedules"][0]["settings_link"] == {
        "section": "timeline",
        "source_name": "screen_time",
    }
    assert body["schedules"][0]["target_state"]["next_run_at"] == 1710000500.0


def test_sensor_schedule_update_is_rejected(monkeypatch):
    client, repository = _build_client(monkeypatch)
    schedule = asyncio.run(_seed_sensor_schedule(repository))

    response = client.patch(
        f"/api/schedules/{schedule.schedule_id}",
        json={"enabled": False},
    )

    assert response.status_code == 409


def test_run_schedule_now_triggers_scheduler_service(monkeypatch):
    client, repository = _build_client(monkeypatch)
    schedule = asyncio.run(_seed_agent_schedule(repository))
    scheduler = _FakeSchedulerService(
        ScheduledExecutionResult(
            success=True,
            message="agent_task_enqueued",
            stats={"background_task_id": "bg_1"},
        )
    )
    monkeypatch.setattr(schedules_module, "require_scheduler_service", lambda: scheduler)

    response = client.post(f"/api/schedules/{schedule.schedule_id}/run")

    assert response.status_code == 200
    assert scheduler.calls == [(schedule.schedule_id, True)]
    body = response.json()
    assert body["schedule"]["schedule_id"] == schedule.schedule_id
    assert body["result"]["success"] is True
    assert body["result"]["message"] == "agent_task_enqueued"
    assert body["result"]["stats"] == {"background_task_id": "bg_1"}


def test_run_schedule_now_rejects_busy_target(monkeypatch):
    client, repository = _build_client(monkeypatch)
    schedule = asyncio.run(_seed_agent_schedule(repository))
    scheduler = _FakeSchedulerService(
        ScheduledExecutionResult(success=False, message="target_busy")
    )
    monkeypatch.setattr(schedules_module, "require_scheduler_service", lambda: scheduler)

    response = client.post(f"/api/schedules/{schedule.schedule_id}/run")

    assert response.status_code == 409
    assert response.json()["detail"] == "Schedule target is busy"


def test_activity_lists_and_cancels_queued_sensor_job(monkeypatch):
    client, repository = _build_client(monkeypatch)
    schedule = asyncio.run(_seed_sensor_schedule(repository))

    async def seed_job() -> str:
        execution_id = await repository.create_execution_record(
            schedule_id=schedule.schedule_id,
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            manual=False,
            started_at=time.time(),
        )
        job_id = await repository.enqueue_sensor_sync_job(
            schedule=schedule,
            execution_id=execution_id,
            manual=False,
        )
        assert job_id is not None
        return job_id

    job_id = asyncio.run(seed_job())

    activity_response = client.get("/api/schedules/activity")
    assert activity_response.status_code == 200
    activities = activity_response.json()["activities"]
    queued = [item for item in activities if item["activity_id"] == f"sensor_job:{job_id}"]
    assert queued
    assert queued[0]["cancellable"] is True

    cancel_response = client.post(
        f"/api/schedules/activity/sensor_job:{job_id}/cancel",
        json={"reason": "user_clicked_stop"},
    )

    assert cancel_response.status_code == 200
    job = asyncio.run(repository.get_sensor_sync_job(job_id))
    assert job is not None
    assert job["status"] == "cancelled"
    assert job["result_message"] == "user_clicked_stop"

