from __future__ import annotations

import pytest

import asyncio
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import schedules as schedules_module
from magi.api.routers.schedules import schedules_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.i18n import language_context
from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.repository import ScheduleRepository
from magi.scheduler import SchedulerService
from pathlib import Path


def _build_client(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(schedules_router, _PUBLIC_ROUTE_METHODS["schedules"]), prefix="/api/schedules")
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


async def _seed_source_schedule(repository: ScheduleRepository) -> ScheduleDefinition:
    await repository.initialize()
    schedule = ScheduleDefinition(
        schedule_id="source-sync:screen-time:screen_time",
        target_type=ScheduledTargetType.SOURCE_SYNC,
        target_key="screen-time:screen_time",
        trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": 300}),
        target_payload={"plugin_id": "screen-time", "source_type": "screen_time"},
        metadata={"plugin_id": "screen-time", "source_type": "screen_time"},
        job_id="source-sync:screen-time:screen_time",
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


def test_list_schedules_includes_target_state_and_source_policy(monkeypatch):
    client, repository = _build_client(monkeypatch)
    asyncio.run(_seed_source_schedule(repository))

    response = client.get("/api/schedules", params={"enabled_only": True})

    assert response.status_code == 200
    body = response.json()
    assert body["schedules"][0]["schedule_id"] == "source-sync:screen-time:screen_time"
    assert body["schedules"][0]["editable"] is False
    assert body["schedules"][0]["settings_link"] == {
        "section": "timeline",
        "source_name": "screen_time",
    }
    # next_run_at is sourced from the APScheduler jobstore, not target_state.
    # In this test environment there is no live apscheduler_jobs table,
    # so the value is None (correct — no pending job is registered).
    assert body["schedules"][0]["target_state"]["next_run_at"] is None


def test_source_schedule_update_is_rejected(monkeypatch):
    client, repository = _build_client(monkeypatch)
    schedule = asyncio.run(_seed_source_schedule(repository))

    response = client.patch(
        f"/api/schedules/{schedule.schedule_id}",
        json={"enabled": False},
    )

    assert response.status_code == 409


def test_public_schedule_writes_register_jobs_and_require_read_revision(monkeypatch):
    client, repository = _build_client(monkeypatch)
    service = SchedulerService(db_path=repository._db_path, runtime_dir=Path(repository._db_path).parent, repository=repository)
    monkeypatch.setattr(schedules_module, "require_scheduler_service", lambda: service)
    body = {"schedule_id": "client-retry", "target_type": "user_agent_task", "target_key": "client-retry", "trigger": {"trigger_type": "interval", "config": {"seconds": 3600}}, "target_payload": {"prompt": "test"}}
    with client:
        client.portal.call(service.start)
        try:
            first = client.post("/api/schedules", json=body)
            assert first.status_code == 201
            revision = first.json()["schedule"]["revision"]
            assert service._scheduler.get_job("client-retry") is not None
            assert client.post("/api/schedules", json=body).json()["schedule"]["revision"] == revision
            assert client.patch("/api/schedules/client-retry", json={"enabled": False}).status_code == 428
            paused = client.patch("/api/schedules/client-retry", json={"enabled": False, "revision": revision})
            assert paused.status_code == 200
            assert service._scheduler.get_job("client-retry") is None
            assert paused.json()["schedule"]["enabled"] is False
            assert client.patch("/api/schedules/client-retry", json={"enabled": True, "revision": revision}).status_code == 409
            assert client.delete("/api/schedules/client-retry", params={"revision": revision}).status_code == 409
            assert client.delete("/api/schedules/client-retry", params={"revision": paused.json()["schedule"]["revision"]}).status_code == 204
            assert client.post("/api/schedules", json=body).status_code == 409
            assert client.get("/api/schedules/client-retry").status_code == 404
        finally:
            client.portal.call(service.stop)


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


@pytest.mark.parametrize(
    "expected_detail,locale",
    [
        pytest.param("Schedule target is busy", "en", id="run_schedule_now_rejects_busy_target"),
        pytest.param(
            "计划任务目标正忙", "zh-CN", id="run_schedule_now_returns_localized_busy_target"
        ),
    ],
)
def test_run_schedule_now_reports_localized_busy_target(monkeypatch, expected_detail, locale):
    client, repository = _build_client(monkeypatch)
    schedule = asyncio.run(_seed_agent_schedule(repository))
    scheduler = _FakeSchedulerService(
        ScheduledExecutionResult(success=False, message="target_busy")
    )
    monkeypatch.setattr(schedules_module, "require_scheduler_service", lambda: scheduler)
    with language_context(locale):
        response = client.post(f"/api/schedules/{schedule.schedule_id}/run")
    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail


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


def test_activity_reads_execution_history_and_filters_before_pagination(monkeypatch):
    client, repository = _build_client(monkeypatch)

    async def seed():
        await repository.initialize()
        for when, target, success in [
            (1, ScheduledTargetType.PERSONA_REFLECTION, True),
            (5, ScheduledTargetType.PERSONA_REFLECTION, True),
            (6, ScheduledTargetType.ATTENTION_WATCH, False),
            (7, ScheduledTargetType.PERSONA_REFLECTION, True),
        ]:
            identity = await repository.create_execution_record(
                schedule_id=target.value, target_type=target, target_key=target.value,
                manual=True, started_at=when,
            )
            await repository.complete_execution_result(
                identity, result=ScheduledExecutionResult(success=success, message="waiting_for_idle"),
                scheduler_job_id=None, finished_at=when + 1,
            )

    asyncio.run(seed())
    params = {"since": 4, "until": 7, "target_types": "persona_reflection", "statuses": "succeeded",
              "limit": 1, "offset": 1}
    response = client.get("/api/schedules/activity", params=params)
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert page["target_type_counts"] == {"persona_reflection": 2, "attention_watch": 1}
    assert page["status_counts"] == {"succeeded": 2, "failed": 1}
    [entry] = page["activities"]
    assert entry["started_at"] == 5 and entry["manual"] and entry["activity_id"].startswith("execution:")
    assert entry["result_message"] == "waiting_for_idle"
    assert client.get("/api/schedules/activity", params={**params, "offset": 2}).json()["activities"] == []


def test_activity_shows_one_queued_job_and_settles_cancellation(monkeypatch):
    client, repository = _build_client(monkeypatch)
    schedule = asyncio.run(_seed_source_schedule(repository))
    job = asyncio.run(repository.enqueue_source_sync_execution(schedule=schedule, manual=True, started_at=1))
    path = "/api/schedules/activity"
    page = client.get(path, params={"since": 10}).json()
    [entry] = page["activities"]
    assert page["total"] == 1 and page["status_counts"] == {"queued": 1}
    assert entry["activity_id"] == f"source_job:{job.job_id}" and entry["cancellable"]
    url = f"{path}/{entry['activity_id']}/cancel"
    assert client.post(url).status_code == 200
    assert client.post(url).status_code == 409
    [entry] = client.get(path).json()["activities"]
    assert entry["activity_id"] == f"execution:{job.execution_id}"
    assert entry["status"] == "cancelled" and not entry["cancellable"]
    assert not asyncio.run(repository.get_schedule_runtime_state(schedule)).running


def test_execution_history_routes_use_scheduler_owner(monkeypatch):
    client, repository = _build_client(monkeypatch)

    async def seed():
        await repository.initialize()
        first = await repository.create_execution_record(schedule_id="one", target_type=ScheduledTargetType.SOURCE_SYNC, target_key="source", manual=True, started_at=1.0)
        second = await repository.create_execution_record(schedule_id="two", target_type=ScheduledTargetType.SOURCE_SYNC, target_key="source", manual=False, started_at=2.0)
        return first, second

    first, second = asyncio.run(seed())
    response = client.get("/api/schedules/executions/recent?limit=1")
    assert response.status_code == 200
    assert [entry["execution_id"] for entry in response.json()["executions"]] == [second]
    response = client.get("/api/schedules/one/executions")
    assert response.status_code == 200
    assert response.json()["executions"][0]["execution_id"] == first
    assert response.json()["executions"][0]["manual"] is True
    assert client.get("/api/schedules/missing/executions").json() == {"executions": []}
