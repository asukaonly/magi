from __future__ import annotations

import asyncio
import tempfile
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import schedules as schedules_module
from magi.api.routers.schedules import schedules_router
from magi.i18n import language_context
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

    async def execute_schedule_async(
        self,
        schedule_id: str,
        *,
        manual: bool = True,
        override_payload: dict | None = None,
    ) -> ScheduledExecutionResult:
        # The run-now route dispatches the fire-and-forget variant now.
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
    # next_run_at is sourced from the APScheduler jobstore, not target_state.
    # In this test environment there is no live apscheduler_jobs table,
    # so the value is None (correct — no pending job is registered).
    assert body["schedules"][0]["target_state"]["next_run_at"] is None


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

    with language_context("en"):
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

    with language_context("en"):
        response = client.post(f"/api/schedules/{schedule.schedule_id}/run")

    assert response.status_code == 409
    assert response.json()["detail"] == "Schedule target is busy"


def test_run_schedule_now_returns_localized_busy_target(monkeypatch):
    client, repository = _build_client(monkeypatch)
    schedule = asyncio.run(_seed_agent_schedule(repository))
    scheduler = _FakeSchedulerService(
        ScheduledExecutionResult(success=False, message="target_busy")
    )
    monkeypatch.setattr(schedules_module, "require_scheduler_service", lambda: scheduler)

    with language_context("zh-CN"):
        response = client.post(f"/api/schedules/{schedule.schedule_id}/run")

    assert response.status_code == 409
    assert response.json()["detail"] == "计划任务目标正忙"


def test_list_schedules_uses_schedule_specific_execution_state(monkeypatch):
    client, repository = _build_client(monkeypatch)

    async def seed_shared_target_schedules() -> None:
        await repository.initialize()
        for period in ("hour", "day", "week"):
            schedule = ScheduleDefinition(
                schedule_id=f"memory-l3-summary:{period}",
                target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                target_key="memory_l3_summary",
                trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": 3600}),
                target_payload={"period_type": period},
                job_id=f"memory-l3-summary:{period}",
            )
            await repository.upsert_schedule(schedule)
        execution_id = await repository.create_execution_record(
            schedule_id="memory-l3-summary:week",
            target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
            target_key="memory_l3_summary",
            manual=True,
            started_at=1710000000.0,
        )
        await repository.complete_execution_result(
            execution_id,
            result=ScheduledExecutionResult(
                success=True,
                message="generated",
                stats={"period_type": "week", "generated": True},
            ),
            scheduler_job_id="memory-l3-summary:week",
            finished_at=1710000003.0,
        )

    asyncio.run(seed_shared_target_schedules())

    response = client.get("/api/schedules", params={"enabled_only": True})

    assert response.status_code == 200
    schedules = {
        item["schedule_id"]: item
        for item in response.json()["schedules"]
        if str(item["schedule_id"]).startswith("memory-l3-summary:")
    }
    assert schedules["memory-l3-summary:week"]["target_state"]["last_run_at"] == 1710000000.0
    assert schedules["memory-l3-summary:week"]["target_state"]["stats"] == {
        "period_type": "week",
        "generated": True,
    }
    assert schedules["memory-l3-summary:hour"]["target_state"]["last_run_at"] is None
    assert schedules["memory-l3-summary:day"]["target_state"]["last_run_at"] is None


# NOTE: test_activity_lists_and_cancels_queued_sensor_job was removed.
# ff2bc71e reverted the Python schedule-activity additions ("Rust gateway
# owns this route") and dropped ScheduleRepository.list_outstanding_sensor_sync_jobs;
# the test exercised that deliberately-reverted Python route. (The leftover
# Python /activity handler still references the dropped repository method —
# tracked separately as dead code.)

