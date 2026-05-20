"""Tests that the schedule activity endpoint surfaces history rows."""

from __future__ import annotations

import time
from importlib import import_module
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.schedules import schedules_router
from magi.core.sqlite import sqlite_connection_async
from magi.scheduler.contracts import ScheduledExecutionResult, ScheduledTargetType
from magi.scheduler.repository import ScheduleRepository
from magi.utils.runtime import RuntimePaths


scheduler_initial = import_module("magi.db.migrations.scheduler.versions.0001_initial")


async def _seed_execution(db_path: Path, *, started_at: float, status: str = "success") -> str:
    async with sqlite_connection_async(db_path) as db:
        await db.executescript(scheduler_initial.SCHEMA_SQL)
    repo = ScheduleRepository(db_path)
    eid = await repo.create_execution_record(
        schedule_id="user-test",
        target_type=ScheduledTargetType.USER_AGENT_TASK,
        target_key="user-test",
        manual=False,
        started_at=started_at,
    )
    if status == "success":
        await repo.complete_execution_success(
            eid,
            result=ScheduledExecutionResult(success=True, message="ok"),
            scheduler_job_id=None,
            finished_at=started_at + 10,
        )
    else:
        await repo.complete_execution_failure(
            eid,
            error="boom",
            scheduler_job_id=None,
            finished_at=started_at + 10,
        )
    return eid


def _build_test_app(runtime_base: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(schedules_router, prefix="/schedules")

    runtime_paths = RuntimePaths(base_dir=runtime_base)
    # The router imports get_runtime_paths at call time, so we monkeypatch the
    # binding in the routers module.
    from magi.api.routers import schedules as schedules_module

    schedules_module.get_runtime_paths = lambda: runtime_paths  # type: ignore[assignment]
    return app


@pytest.mark.asyncio
async def test_activity_endpoint_returns_history_in_window(tmp_path: Path, monkeypatch) -> None:
    runtime_base = tmp_path
    runtime_paths = RuntimePaths(base_dir=runtime_base)
    db_path = Path(runtime_paths.scheduler_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    now = time.time()
    await _seed_execution(db_path, started_at=now - 60, status="success")

    from magi.api.routers import schedules as schedules_module
    monkeypatch.setattr(schedules_module, "get_runtime_paths", lambda: runtime_paths)

    app = FastAPI()
    app.include_router(schedules_router, prefix="/schedules")
    client = TestClient(app)

    resp = client.get(
        "/schedules/activity",
        params={"since": now - 300, "until": now + 1, "limit": 50},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    activities = body["activities"]
    matches = [a for a in activities if a["activity_id"].startswith("execution:")]
    assert matches, f"expected execution rows in activities, got {[a['activity_id'] for a in activities]}"
    first = matches[0]
    assert first["status"] == "succeeded"  # display-status mapping applied
    assert first["schedule_id"] == "user-test"


@pytest.mark.asyncio
async def test_activity_endpoint_status_filter(tmp_path: Path, monkeypatch) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    db_path = Path(runtime_paths.scheduler_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    now = time.time()
    await _seed_execution(db_path, started_at=now - 100, status="success")
    await _seed_execution(db_path, started_at=now - 50, status="failed")

    from magi.api.routers import schedules as schedules_module
    monkeypatch.setattr(schedules_module, "get_runtime_paths", lambda: runtime_paths)

    app = FastAPI()
    app.include_router(schedules_router, prefix="/schedules")
    client = TestClient(app)

    resp = client.get(
        "/schedules/activity",
        params={"since": now - 300, "until": now + 1, "limit": 50, "statuses": "failed"},
    )
    assert resp.status_code == 200
    statuses = [a["status"] for a in resp.json()["activities"] if a["activity_id"].startswith("execution:")]
    assert statuses == ["failed"]
