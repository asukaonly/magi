"""Public chat routes retain mutation semantics after gateway ownership removal."""
from _shared.chat_stores import build_chat_reader

import asyncio
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers import messages_sessions
from magi.api.routers.messages import user_messages_router
from magi.chat.storage.workspace_preferences import JsonRecentWorkspaceRepository
from magi.utils.runtime import RuntimePaths


@pytest.fixture
def chat_client(tmp_path, ensure_db_schema, monkeypatch):
    paths = RuntimePaths(tmp_path / "center")
    ensure_db_schema("chat", str(paths.chat_db_path))
    service = build_chat_reader(runtime_paths=paths)
    monkeypatch.setattr(messages_sessions, "require_chat_read_service", lambda: service)
    monkeypatch.setattr(messages_sessions, "get_default_chat_workspace_path", lambda: None)
    app = FastAPI()
    app.include_router(
        _build_public_router(user_messages_router, _PUBLIC_ROUTE_METHODS["messages"]),
        prefix="/api/messages",
    )
    with TestClient(app) as client:
        yield client, paths
    service.close()


def test_public_creation_retry_and_terminal_conflict(chat_client):
    client, paths = chat_client
    url = "/api/messages/session/new?user_id=local_user&idempotency_key=stable_1"
    first = client.post(url)
    assert first.status_code == 201
    assert client.post(url).json() == first.json()
    session_id = first.json()["session_id"]
    assert session_id != "stable_1"
    with sqlite3.connect(paths.chat_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 1
        connection.execute(
            "UPDATE chat_sessions SET archived_at_ms=1 WHERE session_id=?", (session_id,)
        )
    assert client.post(url).status_code == 409


def test_public_session_mutations_require_ownership(chat_client):
    client, _ = chat_client
    session_id = client.post("/api/messages/session/new?user_id=local_user").json()["session_id"]
    path = f"/api/messages/session/{session_id}"
    assert client.patch(path, json={"user_id": "other", "title": "foreign"}).status_code == 404
    response = client.patch(path, json={"user_id": "local_user", "title": "Renamed"})
    assert response.status_code == 200 and response.json()["session"]["title"] == "Renamed"
    assert (
        client.patch(
            path + "/workspace", json={"user_id": "other", "workspace_path": None}
        ).status_code
        == 404
    )


def test_recent_workspaces_are_publicly_reachable_and_persisted(chat_client):
    client, paths = chat_client
    url = "/api/messages/workspaces/recent"
    assert client.get(url).json() == {"paths": []}
    for name in ["one", "two", "three", "four", "five", "two", "six"]:
        assert client.post(url, json={"path": f" /{name} "}).status_code == 200
    assert client.get(url).json() == {"paths": ["/six", "/two", "/five", "/four", "/three"]}
    restored = JsonRecentWorkspaceRepository(paths.config_dir / "recent_chat_workspaces.json")
    assert asyncio.run(restored.list_paths()) == client.get(url).json()["paths"]
    assert client.post(url, json={"path": " "}).status_code == 400


@pytest.mark.asyncio
async def test_workspace_repository_serializes_concurrent_updates(tmp_path):
    repository = JsonRecentWorkspaceRepository(tmp_path / "recent.json")
    await asyncio.gather(*(repository.remember(f"/{number}") for number in range(5)))
    assert set(await repository.list_paths()) == {f"/{number}" for number in range(5)}


def test_creation_storage_failure_is_not_reported_as_success(chat_client, monkeypatch):
    client, _ = chat_client

    def unavailable():
        raise RuntimeError("Not initialized")

    monkeypatch.setattr(messages_sessions, "require_chat_read_service", unavailable)
    assert client.post("/api/messages/session/new").status_code == 503
