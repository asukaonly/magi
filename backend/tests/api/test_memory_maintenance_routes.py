from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router, maintenance_routes
from magi.config.memory_models import MemorySettings
from magi.scheduler import SchedulerService, ScheduledTargetType, ScheduledExecutionResult
from magi.memory.l1.maintenance_schedule import SCHEDULE_ID_L1_MAINTENANCE
from magi.memory.l3.summary_schedule import SCHEDULE_ID_L3_HOUR

from _shared.memory_api import MemoryApiStub


@pytest.mark.asyncio
async def test_maintenance_status_uses_runtime_config_jobs_and_history(tmp_path, monkeypatch):
    cfg = MemorySettings()
    scheduler = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    monkeypatch.setattr(
        maintenance_routes, "get_config", lambda: SimpleNamespace(agent=SimpleNamespace(memory=cfg))
    )
    monkeypatch.setattr(maintenance_routes.dependencies, "_resolve_scheduler_service", lambda: scheduler)
    unified = MemoryApiStub(
        l1=object(), l2=object(), l2_entity_catalog=object(), l3=object(), l4=object()
    )
    monkeypatch.setattr(maintenance_routes.dependencies, "_resolve_unified_memory", lambda: unified)
    await scheduler.start(paused=True)
    try:

        async def handler(_context):
            return ScheduledExecutionResult(success=False, message="Maintenance failed")

        scheduler.register_handler(ScheduledTargetType.MEMORY_L1_MAINTENANCE, handler)
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_L1_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L1_MAINTENANCE,
            target_key="memory_l1_maintenance",
            seconds=3600,
            target_payload={},
        )
        app = FastAPI()
        app.include_router(
            _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
            prefix="/api/memory",
        )

        def read():
            response = TestClient(app).get("/api/memory/maintenance/tasks")
            assert response.status_code == 200
            return {item["id"]: item for item in response.json()["tasks"]}

        assert read()["events"]["status"] == "paused"
        await scheduler.activate()
        assert read()["events"]["status"] == "enabled"
        assert read()["summary"]["status"] == "unavailable"
        cfg.l1.maintenance_enabled = False
        assert read()["events"]["status"] == "disabled"

        async def skip_handler(_context):
            return ScheduledExecutionResult(success=True, message="l1_maintenance_disabled_skip")

        scheduler.register_handler(ScheduledTargetType.MEMORY_L1_MAINTENANCE, skip_handler)
        await scheduler.trigger_now(SCHEDULE_ID_L1_MAINTENANCE)
        assert read()["events"]["last_result"] == "skipped"
        cfg.l1.maintenance_enabled = True
        scheduler.register_handler(ScheduledTargetType.MEMORY_L1_MAINTENANCE, handler)
        await scheduler.trigger_now(SCHEDULE_ID_L1_MAINTENANCE)
        events = read()["events"]
        assert events["last_result"] == "failed"
        assert events["last_run_at"] is not None
        definition = await scheduler.repository.get_schedule(SCHEDULE_ID_L1_MAINTENANCE)
        scheduler._scheduler.pause_job(definition.job_id or definition.schedule_id)
        assert read()["events"]["status"] == "paused"
        definition.enabled = False
        await scheduler.schedule(definition)
        assert read()["events"]["status"] == "paused"
        assert read()["events"]["last_result"] == "failed"
        definition.enabled = True
        await scheduler.schedule(definition)
        scheduler._scheduler.remove_job(definition.job_id or definition.schedule_id)
        assert read()["events"]["status"] == "unavailable"

        scheduler.register_handler(ScheduledTargetType.MEMORY_L3_SUMMARY, handler)
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_L3_HOUR,
            target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
            target_key="memory_l3_summary",
            seconds=3600,
            target_payload={},
        )
        summary = read()["summary"]
        assert summary["status"] == "partial"
        assert summary["enabled_count"] == 1
        assert summary["schedule_count"] == 5
        unified.l3 = None
        assert read()["summary"]["status"] == "unavailable"
        cfg.l3.maintenance_enabled = False
        assert read()["summary"]["status"] == "unavailable"
        cfg.l3.enabled = False
        assert read()["summary"]["status"] == "disabled"
    finally:
        await scheduler.stop()


@pytest.mark.parametrize("enabled", [False, True])
def test_maintenance_lists_every_task_when_runtime_is_unavailable(monkeypatch, enabled):
    cfg = MemorySettings()
    for layer in (cfg.l1, cfg.l2, cfg.l3, cfg.l4):
        layer.enabled = enabled
        layer.maintenance_enabled = True
    cfg.l2.derive_schedule_enabled = True
    cfg.l2.consolidation_enabled = True
    monkeypatch.setattr(
        maintenance_routes, "get_config", lambda: SimpleNamespace(agent=SimpleNamespace(memory=cfg))
    )
    monkeypatch.setattr(maintenance_routes.dependencies, "_resolve_scheduler_service", lambda: None)
    monkeypatch.setattr(maintenance_routes.dependencies, "_resolve_unified_memory", lambda: None)
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    response = TestClient(app).get("/api/memory/maintenance/tasks")
    assert response.status_code == 200
    assert response.json() == {
        "tasks": [
            {
                "id": task_id,
                "status": "unavailable" if enabled else "disabled",
                "schedule_count": count,
                "enabled_count": 0,
                "last_run_at": None,
                "last_result": None,
            }
            for task_id, count in [
                ("events", 1),
                ("structure", 3),
                ("chapter", 1),
                ("summary", 5),
                ("skills", 1),
            ]
        ]
    }
