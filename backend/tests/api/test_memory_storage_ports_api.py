"""Public memory routes accept repositories without filesystem identities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from _shared.memory_api import MemoryApiStub

from magi.api.routers.memory import memory_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router


def test_knowledge_and_context_routes_use_pathless_repositories(monkeypatch):
    presentation = SimpleNamespace(
        get_canonical_names=AsyncMock(return_value={"entity-1": "Garden"}),
        decorate_assertions=AsyncMock(return_value=[{"assertion_id": "assertion-1"}]),
    )
    contexts = SimpleNamespace(sync_workspace_project_options=AsyncMock(return_value=[]))
    store = SimpleNamespace(
        presentation=presentation,
        context_catalog=contexts,
        get_relationships=AsyncMock(return_value=[{"object_id": "entity-1"}]),
        count_relationships=AsyncMock(return_value=1),
        list_tom_assertions=AsyncMock(return_value=[{"assertion_id": "assertion-1"}]),
        count_tom_assertions=AsyncMock(return_value=1),
    )
    memory = MemoryApiStub(l2=store, identity_resolver=None)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: SimpleNamespace(alist_workspace_paths=AsyncMock(return_value=["/workspace/garden"])),
    )
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    client = TestClient(app)
    response = client.get("/api/memory/l2/relations")
    assert response.status_code == 200
    assert response.json()["items"][0]["object_name"] == "Garden"
    assert client.get("/api/memory/l2/assertions").json()["items"] == [{"assertion_id": "assertion-1"}]
    response = client.get("/api/memory/l2/context-options")
    assert response.status_code == 200
    assert response.json() == {"items": []}
    contexts.sync_workspace_project_options.assert_awaited_once_with(["/workspace/garden"])
