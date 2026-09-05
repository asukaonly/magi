"""Public experience processing status and bounded scheduling contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.l2 import consolidation_routes as routes
from magi.api.routers.memory.router import memory_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.config.models import MemoryL2Settings
from magi.memory.l2 import consolidation_schedule


@pytest.fixture
def surface(monkeypatch):
    settings = MemoryL2Settings()
    config = SimpleNamespace(agent=SimpleNamespace(memory=SimpleNamespace(l2=settings)))
    state = SimpleNamespace(
        running=False, last_error=None, last_run_at=None, last_success_at=None, stats={}
    )
    scheduler = SimpleNamespace(
        get_target_state=AsyncMock(return_value=state),
        get_schedule=AsyncMock(return_value=None),
        schedule_once_earliest=AsyncMock(),
    )
    unified = SimpleNamespace(
        l2=SimpleNamespace(get_projection_backlog_stats=AsyncMock(return_value={})),
        scenario_llm_pool=None,
    )
    monkeypatch.setattr(routes, "get_config", lambda: config)
    monkeypatch.setattr(consolidation_schedule, "get_config", lambda: config)
    monkeypatch.setattr(routes, "_resolve_unified_memory", lambda: unified)
    monkeypatch.setattr(routes, "_resolve_scheduler_service", lambda: scheduler)
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    return TestClient(app), state, scheduler, unified, settings


@pytest.mark.parametrize(
    "stats,error,expected",
    [
        ({}, None, "insufficient_evidence"),
        ({"experience_deferred": 3}, None, "model_budget"),
        ({"experiences_promoted": 1}, None, "ready"),
        ({"experiences_promoted": 1}, "consolidation_partial_failure", "partial_failure"),
        ({"experiences_promoted": 1}, "private failure details", "failed"),
    ],
)
def test_completed_status_exposes_safe_reason(surface, stats, error, expected):
    client, state, _, _, _ = surface
    state.stats, state.last_error, state.last_run_at = stats, error, 100
    response = client.get("/api/memory/l2/consolidation")
    assert response.status_code == 200
    assert response.json()["reason_code"] == expected
    assert "private failure details" not in response.text


def test_not_run_backlog_running_and_queued(surface):
    client, state, scheduler, unified, _ = surface
    assert client.get("/api/memory/l2/consolidation").json()["reason_code"] == "not_run"
    unified.l2.get_projection_backlog_stats.return_value = {
        "pending": 2,
        "claimed": 3,
        "queued": 2,
        "running": 1,
    }
    data = client.get("/api/memory/l2/consolidation").json()
    assert data["pending_events"] == 5
    assert data["reason_code"] == "processing_events"
    scheduler.get_schedule.return_value = SimpleNamespace(enabled=True)
    assert client.get("/api/memory/l2/consolidation").json()["state"] == "queued"
    state.running = True
    assert client.get("/api/memory/l2/consolidation").json()["state"] == "running"


def test_requests_coalesce_and_respect_disabled_config(surface):
    client, _, scheduler, _, settings = surface
    for _ in range(2):
        assert client.post("/api/memory/l2/consolidation").json() == {"scheduled": True}
    calls = scheduler.schedule_once_earliest.await_args_list
    assert {call.kwargs["schedule_id"] for call in calls} == {"memory-l2-consolidate:requested"}
    assert {call.kwargs["target_key"] for call in calls} == {"memory_l2_consolidate"}
    settings.consolidation_enabled = False
    assert client.post("/api/memory/l2/consolidation").json() == {"scheduled": False}
    assert client.get("/api/memory/l2/consolidation").json()["state"] == "disabled"
    assert scheduler.schedule_once_earliest.await_count == 2
