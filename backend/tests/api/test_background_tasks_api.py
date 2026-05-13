"""Tests for the /api/background-tasks router."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)
from magi.api.routers import background_tasks as background_tasks_module
from magi.api.routers.background_tasks import background_tasks_router


class _FakeManager:
    """Manager stub exposing the bits the router needs."""

    def __init__(self, store: BackgroundTaskStore) -> None:
        self._store = store
        self.cancel_calls: list[tuple[str, str]] = []
        self.retry_calls: list[str] = []
        self._cancel_ok = True
        self._retry_task: BackgroundTask | None = None
        self._active = 0

    @property
    def store(self) -> BackgroundTaskStore:
        return self._store

    def active_count(self) -> int:
        return self._active

    def set_active(self, value: int) -> None:
        self._active = value

    async def cancel(self, task_id: str, *, reason: str = "user_requested") -> bool:
        self.cancel_calls.append((task_id, reason))
        return self._cancel_ok

    def set_cancel_ok(self, value: bool) -> None:
        self._cancel_ok = value

    async def retry(self, task_id: str) -> BackgroundTask | None:
        self.retry_calls.append(task_id)
        return self._retry_task

    def set_retry_task(self, task: BackgroundTask | None) -> None:
        self._retry_task = task


def _make_spec(**overrides) -> BackgroundTaskSpec:
    defaults: dict = dict(
        user_id="u1",
        session_id="s1",
        origin_turn_id="t1",
        title="Demo",
        goal="Do things",
        selected_tools=[],
        trigger_source=BackgroundTaskTriggerSource.RULE,
    )
    defaults.update(overrides)
    return BackgroundTaskSpec(**defaults)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))
    manager = _FakeManager(store)
    app = FastAPI()
    app.include_router(background_tasks_router, prefix="/api/background-tasks")
    monkeypatch.setattr(
        background_tasks_module,
        "resolve_background_task_manager",
        lambda: manager,
    )
    return TestClient(app), manager, store


@pytest.mark.asyncio
async def _seed(store: BackgroundTaskStore, *, status=BackgroundTaskStatus.PENDING):
    task = BackgroundTask.new(_make_spec())
    task.status = status
    await store.create_task(task)
    return task


def test_list_returns_empty_when_no_tasks(client):
    tc, manager, _store = client
    manager.set_active(0)
    response = tc.get("/api/background-tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["tasks"] == []
    assert data["active_count"] == 0
    assert data["total"] == 0


def test_list_returns_tasks_and_active_count(client):
    tc, manager, store = client
    import asyncio

    async def seed():
        await _seed(store, status=BackgroundTaskStatus.RUNNING)
        await _seed(store, status=BackgroundTaskStatus.PENDING)

    asyncio.run(seed())
    manager.set_active(1)
    response = tc.get("/api/background-tasks")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tasks"]) == 2
    assert data["active_count"] == 1
    assert data["total"] == 2


def test_list_applies_limit_offset_and_reports_total(client):
    tc, _manager, store = client
    import asyncio

    async def seed():
        first = await _seed(store, status=BackgroundTaskStatus.SUCCEEDED)
        second = await _seed(store, status=BackgroundTaskStatus.SUCCEEDED)
        third = await _seed(store, status=BackgroundTaskStatus.SUCCEEDED)
        return first, second, third

    first, second, third = asyncio.run(seed())
    response = tc.get("/api/background-tasks", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_id"] == second.task_id


def test_list_filters_by_status(client):
    tc, _manager, store = client
    import asyncio

    async def seed():
        await _seed(store, status=BackgroundTaskStatus.SUCCEEDED)
        await _seed(store, status=BackgroundTaskStatus.PENDING)

    asyncio.run(seed())
    response = tc.get("/api/background-tasks", params={"status": "pending"})
    data = response.json()
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["status"] == "pending"


def test_list_rejects_invalid_status(client):
    tc, *_ = client
    response = tc.get("/api/background-tasks", params={"status": "bogus"})
    assert response.status_code == 400


def test_get_returns_task_and_events(client):
    tc, _manager, store = client
    import asyncio

    async def seed():
        return await _seed(store, status=BackgroundTaskStatus.RUNNING)

    task = asyncio.run(seed())
    response = tc.get(f"/api/background-tasks/{task.task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["task"]["task_id"] == task.task_id
    assert isinstance(data["events"], list)


def test_get_returns_404_for_unknown_id(client):
    tc, *_ = client
    response = tc.get("/api/background-tasks/nope")
    assert response.status_code == 404


def test_cancel_invokes_manager_with_reason(client):
    tc, manager, store = client
    import asyncio

    async def seed():
        return await _seed(store, status=BackgroundTaskStatus.RUNNING)

    task = asyncio.run(seed())
    response = tc.post(
        f"/api/background-tasks/{task.task_id}/cancel",
        json={"reason": "user_click"},
    )
    assert response.status_code == 200
    assert manager.cancel_calls == [(task.task_id, "user_click")]


def test_cancel_defaults_reason_when_body_missing(client):
    tc, manager, store = client
    import asyncio

    async def seed():
        return await _seed(store, status=BackgroundTaskStatus.RUNNING)

    task = asyncio.run(seed())
    response = tc.post(f"/api/background-tasks/{task.task_id}/cancel")
    assert response.status_code == 200
    assert manager.cancel_calls == [(task.task_id, "user_requested")]


def test_cancel_returns_404_for_unknown(client):
    tc, manager, _store = client
    manager.set_cancel_ok(False)
    response = tc.post("/api/background-tasks/nope/cancel")
    assert response.status_code == 404


def test_cancel_returns_409_when_not_cancellable(client):
    tc, manager, store = client
    import asyncio

    async def seed():
        return await _seed(store, status=BackgroundTaskStatus.SUCCEEDED)

    task = asyncio.run(seed())
    manager.set_cancel_ok(False)
    response = tc.post(f"/api/background-tasks/{task.task_id}/cancel")
    assert response.status_code == 409


def test_retry_returns_new_attempt(client):
    tc, manager, store = client
    import asyncio

    async def seed():
        return await _seed(store, status=BackgroundTaskStatus.FAILED)

    task = asyncio.run(seed())
    manager.set_retry_task(task)
    response = tc.post(f"/api/background-tasks/{task.task_id}/retry")
    assert response.status_code == 200
    assert manager.retry_calls == [task.task_id]


def test_retry_returns_409_when_not_retriable(client):
    tc, manager, store = client
    import asyncio

    async def seed():
        return await _seed(store, status=BackgroundTaskStatus.RUNNING)

    task = asyncio.run(seed())
    manager.set_retry_task(None)
    response = tc.post(f"/api/background-tasks/{task.task_id}/retry")
    assert response.status_code == 409


def test_dismiss_deletes_terminal_row(client):
    tc, _manager, store = client
    import asyncio

    async def seed():
        return await _seed(store, status=BackgroundTaskStatus.SUCCEEDED)

    task = asyncio.run(seed())
    response = tc.post(f"/api/background-tasks/{task.task_id}/dismiss")
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_dismiss_rejects_non_terminal(client):
    tc, _manager, store = client
    import asyncio

    async def seed():
        return await _seed(store, status=BackgroundTaskStatus.RUNNING)

    task = asyncio.run(seed())
    response = tc.post(f"/api/background-tasks/{task.task_id}/dismiss")
    assert response.status_code == 409
