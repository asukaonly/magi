from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import personas as personas_module
from magi.api.routers.personas import personas_router
from magi.personality.persona_repository import PersonaRepository


_SAMPLE_CONFIG = json.dumps(
    {
        "meta": {"group": "test", "order": 1},
        "name": "Trace Persona",
        "description": "Persona used by active switch characterization.",
        "avatar": "trace.jpg",
        "identity_core": {
            "identity_statement": "A traceable persona used by tests.",
        },
    }
)


def test_set_active_persona_updates_registry_and_live_prompt_state(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    persona_id = asyncio.run(repo.create(_SAMPLE_CONFIG, locale="en", slug="trace_persona"))

    state_calls: list[tuple[str, str]] = []
    reload_calls: list[tuple[str, str]] = []

    def fake_set_current_personality(slug, *, config=None):
        state_calls.append((slug, config.name if config is not None else ""))

    class _FakeMemory:
        async def reload_personality(self, slug, *, personality_config=None):
            reload_calls.append((slug, personality_config.name if personality_config is not None else ""))

    class _FakeManager:
        async def ensure_agent(self, task_agent_type, agent_id):
            _ = (task_agent_type, agent_id)
            return SimpleNamespace(memory=_FakeMemory())

    class _FakeRuntime:
        def get_task_agent_manager(self):
            return _FakeManager()

    monkeypatch.setattr(personas_module, "_get_repo", lambda: repo)
    monkeypatch.setattr("magi.personality.active_persona.set_current_personality", fake_set_current_personality)
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", lambda: _FakeRuntime())

    app = FastAPI()
    app.include_router(personas_router, prefix="/api/personas")

    response = TestClient(app).put("/api/personas/active", json={"persona_id": persona_id})

    assert response.status_code == 200
    assert response.json()["persona_id"] == persona_id
    assert asyncio.run(repo.get_active_id()) == persona_id
    assert state_calls == [("trace_persona", "Trace Persona")]
    assert reload_calls == [("trace_persona", "Trace Persona")]


def test_list_personas_can_include_soft_deleted_records(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    persona_id = asyncio.run(repo.create(_SAMPLE_CONFIG, locale="en", slug="deleted_persona"))
    asyncio.run(repo.delete(persona_id))

    async def _skip_builtin_sync(_repo):
        return None

    monkeypatch.setattr(personas_module, "_sync_registered_builtin_personas", _skip_builtin_sync)
    client = _build_client(repo, monkeypatch)

    default_response = client.get("/api/personas/")
    include_deleted_response = client.get("/api/personas/?include_deleted=true")

    assert default_response.status_code == 200
    assert default_response.json()["data"] == []
    assert include_deleted_response.status_code == 200
    deleted_items = include_deleted_response.json()["data"]
    assert len(deleted_items) == 1
    assert deleted_items[0]["persona_id"] == persona_id
    assert deleted_items[0]["deleted_at"] is not None


def _build_client(repo: PersonaRepository, monkeypatch) -> TestClient:
    monkeypatch.setattr(personas_module, "_get_repo", lambda: repo)
    app = FastAPI()
    app.include_router(personas_router, prefix="/api/personas")
    return TestClient(app)


def test_get_persona_not_found_returns_localized_detail(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    client = _build_client(repo, monkeypatch)

    response = client.get("/api/personas/missing", headers={"Accept-Language": "zh-CN"})

    assert response.status_code == 404
    assert response.json()["detail"] == "未找到人格"


def test_create_persona_invalid_config_returns_localized_detail(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    client = _build_client(repo, monkeypatch)

    response = client.post(
        "/api/personas/",
        json={"config_json": "{bad", "locale": "zh"},
        headers={"Accept-Language": "zh-CN"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "人格配置 JSON 无效"


def test_delete_active_persona_returns_localized_conflict(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    persona_id = asyncio.run(repo.create(_SAMPLE_CONFIG, locale="en", slug="active_persona"))
    asyncio.run(repo.set_active(persona_id))
    client = _build_client(repo, monkeypatch)

    response = client.delete(f"/api/personas/{persona_id}", headers={"Accept-Language": "zh-CN"})

    assert response.status_code == 409
    assert response.json()["detail"] == "不能删除当前启用的人格"
