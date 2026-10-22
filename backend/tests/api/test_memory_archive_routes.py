"""Archive routes are reachable only through the product's public router contract."""

from __future__ import annotations

from types import SimpleNamespace
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import archive_routes, memory_router
from magi.memory.archives.models import ArchiveSearchResult
from memory.test_archive_reader import _archive_event
from memory.test_durable_forgetting import _build_memory


@pytest.fixture
async def archive_memory(tmp_path):
    store = _build_memory(tmp_path)
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


def _client():
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    return TestClient(app)


@asynccontextmanager
async def _operation_guard():
    yield


def _memory_stub(tmp_path):
    return SimpleNamespace(
        _archive_dir=tmp_path,
        memory_db_path=tmp_path / "memory.db",
        memory_operation_epoch=lambda: 0,
        memory_clear_in_progress=lambda: False,
        memory_operation_guard=_operation_guard,
    )


def test_archive_search_reachable_through_public_router_and_typed_response(monkeypatch, tmp_path):
    monkeypatch.setattr(archive_routes.dependencies, "_resolve_unified_memory", lambda: _memory_stub(tmp_path))

    async def search(_reader, **kwargs):
        assert kwargs == {"query": "京都", "limit": 2, "offset": 1, "event_ids": None}
        return ArchiveSearchResult(items=[], total=0, limit=2, offset=1)

    monkeypatch.setattr(archive_routes.ArchiveReader, "search", search)
    response = _client().get(
        "/api/memory/archives/search", params={"query": "京都", "limit": 2, "offset": 1}
    )
    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 2,
        "offset": 1,
        "partial": False,
        "issues": [],
    }
    assert _client().get("/api/memory/archives/search", params={"limit": 101}).status_code == 422
    assert _client().get("/api/memory/archives/search", params={"offset": -1}).status_code == 422
    assert _client().get("/api/memory/archives/search", params={"path": "/tmp"}).status_code == 422
    assert _client().get("/api/memory/archives/search", params={"query": "x" * 2001}).status_code == 422
    assert _client().post("/api/memory/archives/search", json={}).status_code == 405


def test_archive_evidence_exact_filter_is_public_and_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(archive_routes.dependencies, "_resolve_unified_memory", lambda: _memory_stub(tmp_path))

    async def search(_reader, **kwargs):
        assert kwargs["event_ids"] == ("event-one", "event-two")
        return ArchiveSearchResult(items=[], total=0, limit=20, offset=0)

    monkeypatch.setattr(archive_routes.ArchiveReader, "search", search)
    response = _client().get(
        "/api/memory/archives/search", params=[("event_ids", "event-one"), ("event_ids", "event-two")]
    )
    assert response.status_code == 200
    assert _client().get("/api/memory/archives/search", params={"event_ids": ""}).status_code == 422
    assert _client().get("/api/memory/archives/search", params={"event_ids": "x" * 513}).status_code == 422
    assert _client().get(
        "/api/memory/archives/search", params=[("event_ids", str(index)) for index in range(101)]
    ).status_code == 422


def test_unavailable_archive_governance_is_503_and_does_not_leak_path(monkeypatch, tmp_path):
    monkeypatch.setattr(archive_routes.dependencies, "_resolve_unified_memory", lambda: _memory_stub(tmp_path))
    response = _client().get("/api/memory/archives/search")
    assert response.status_code == 503
    assert str(tmp_path) not in response.text


@pytest.mark.asyncio
async def test_public_archive_api_reads_real_archive_and_observes_forgetting(
    archive_memory, monkeypatch
):
    await _archive_event(archive_memory, "api-history", content="历史京都旅行")
    monkeypatch.setattr(archive_routes.dependencies, "_resolve_unified_memory", lambda: archive_memory)
    response = _client().get("/api/memory/archives/search", params={"query": "京都"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1 and not body["partial"]
    assert body["items"][0]["content"] == "历史京都旅行"
    assert body["items"][0]["archived"] is True
    assert body["items"][0]["evidence_event_ids"] == ["api-history"]
    exact = _client().get("/api/memory/archives/search", params={"event_ids": "api-history"})
    assert exact.status_code == 200 and exact.json()["total"] == 1
    await archive_memory.forget_source_events(["api-history"])
    response = _client().get("/api/memory/archives/search", params={"query": "京都"})
    assert response.status_code == 200 and response.json()["total"] == 0
    exact = _client().get("/api/memory/archives/search", params={"event_ids": "api-history"})
    assert exact.status_code == 200 and exact.json()["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["clear", "forget"])
async def test_archive_response_is_fenced_when_governance_changes_during_read(
    archive_memory,
    monkeypatch,
    operation,
):
    await _archive_event(archive_memory, "racing-history")
    monkeypatch.setattr(archive_routes.dependencies, "_resolve_unified_memory", lambda: archive_memory)
    original_search = archive_routes.ArchiveReader.search
    read_completed, release = asyncio.Event(), asyncio.Event()

    async def paused_search(reader, **kwargs):
        result = await original_search(reader, **kwargs)
        assert result.total == 1
        read_completed.set()
        await release.wait()
        return result

    monkeypatch.setattr(archive_routes.ArchiveReader, "search", paused_search)
    query = asyncio.create_task(
        archive_routes.search_archives(archive_routes.ArchiveSearchRequest())
    )
    await asyncio.wait_for(read_completed.wait(), timeout=5)
    if operation == "clear":
        mutation = asyncio.create_task(archive_memory.clear_all_memory())
        await asyncio.sleep(0)
        assert archive_memory.memory_clear_in_progress()
    else:
        mutation = asyncio.create_task(archive_memory.forget_source_events(["racing-history"]))
        await asyncio.wait_for(asyncio.shield(mutation), timeout=5)
    release.set()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(query, timeout=5)
    assert error.value.status_code == 503
    await asyncio.wait_for(mutation, timeout=5)
