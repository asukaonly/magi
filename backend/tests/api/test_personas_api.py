from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

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
    monkeypatch.setattr(
        "magi.core.runtime_bindings.get_optional_agent_runtime",
        lambda: _FakeRuntime(),
    )

    app = FastAPI()
    app.include_router(personas_router, prefix="/api/personas")

    response = TestClient(app).put("/api/personas/active", json={"persona_id": persona_id})

    assert response.status_code == 200
    assert response.json()["persona_id"] == persona_id
    assert asyncio.run(repo.get_active_id()) == persona_id
    assert state_calls == [("trace_persona", "Trace Persona")]
    assert reload_calls == [("trace_persona", "Trace Persona")]


@pytest.mark.asyncio
async def test_concurrent_active_switches_finish_with_the_latest_persona(
    tmp_path,
    monkeypatch,
) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    await repo.init()
    first_id = await repo.create(_SAMPLE_CONFIG, locale="en", slug="first_persona")
    second_config = json.loads(_SAMPLE_CONFIG)
    second_config["name"] = "Second Persona"
    second_id = await repo.create(
        json.dumps(second_config),
        locale="en",
        slug="second_persona",
    )

    first_reload_started = asyncio.Event()
    release_first_reload = asyncio.Event()
    second_reload_finished = asyncio.Event()
    global_slugs: list[str] = []
    memory_slugs: list[str] = []

    def fake_set_current_personality(slug, *, config=None):
        _ = config
        global_slugs.append(slug)

    class _FakeMemory:
        async def reload_personality(self, slug, *, personality_config=None):
            _ = personality_config
            if slug == "first_persona":
                first_reload_started.set()
                await release_first_reload.wait()
            memory_slugs.append(slug)
            if slug == "second_persona":
                second_reload_finished.set()

    class _FakeManager:
        async def ensure_agent(self, task_agent_type, agent_id):
            _ = (task_agent_type, agent_id)
            return SimpleNamespace(memory=_FakeMemory())

    class _FakeRuntime:
        def get_task_agent_manager(self):
            return _FakeManager()

    monkeypatch.setattr(personas_module, "_get_repo", lambda: repo)
    monkeypatch.setattr(
        "magi.personality.active_persona.set_current_personality",
        fake_set_current_personality,
    )
    monkeypatch.setattr(
        "magi.core.runtime_bindings.get_optional_agent_runtime",
        lambda: _FakeRuntime(),
    )
    request = SimpleNamespace(headers={})

    first_switch = asyncio.create_task(
        personas_module.set_active_persona(
            request,
            personas_module.ActivePersonaRequest(persona_id=first_id),
        )
    )
    await first_reload_started.wait()
    second_switch = asyncio.create_task(
        personas_module.set_active_persona(
            request,
            personas_module.ActivePersonaRequest(persona_id=second_id),
        )
    )
    try:
        await asyncio.wait_for(second_reload_finished.wait(), timeout=0.1)
    except TimeoutError:
        pass
    release_first_reload.set()

    first_response, second_response = await asyncio.gather(first_switch, second_switch)

    assert first_response.persona_id == first_id
    assert second_response.persona_id == second_id
    assert await repo.get_active_id() == second_id
    assert global_slugs[-1] == "second_persona"
    assert memory_slugs[-1] == "second_persona"


def test_set_active_persona_rolls_back_when_live_reload_fails(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    previous_id = asyncio.run(
        repo.create(_SAMPLE_CONFIG, locale="en", slug="previous_persona")
    )
    target_config = json.loads(_SAMPLE_CONFIG)
    target_config["name"] = "Target Persona"
    target_id = asyncio.run(
        repo.create(
            json.dumps(target_config),
            locale="en",
            slug="target_persona",
        )
    )
    asyncio.run(repo.set_active(previous_id))

    global_slugs: list[str] = []
    reload_slugs: list[str] = []

    def fake_set_current_personality(slug, *, config=None):
        _ = config
        global_slugs.append(slug)

    class _FakeMemory:
        async def reload_personality(self, slug, *, personality_config=None):
            _ = personality_config
            reload_slugs.append(slug)
            if slug == "target_persona":
                raise RuntimeError("reload failed")

    class _FakeManager:
        async def ensure_agent(self, task_agent_type, agent_id):
            _ = (task_agent_type, agent_id)
            return SimpleNamespace(memory=_FakeMemory())

    class _FakeRuntime:
        def get_task_agent_manager(self):
            return _FakeManager()

    monkeypatch.setattr(personas_module, "_get_repo", lambda: repo)
    monkeypatch.setattr(
        "magi.personality.active_persona.set_current_personality",
        fake_set_current_personality,
    )
    monkeypatch.setattr(
        "magi.core.runtime_bindings.get_optional_agent_runtime",
        lambda: _FakeRuntime(),
    )
    client = _build_client(repo, monkeypatch)

    response = client.put(
        "/api/personas/active",
        json={"persona_id": target_id},
        headers={"Accept-Language": "en"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Failed to activate persona"
    assert asyncio.run(repo.get_active_id()) == previous_id
    assert global_slugs == ["target_persona", "previous_persona"]
    assert reload_slugs == ["target_persona", "previous_persona"]


def test_set_active_persona_succeeds_before_runtime_is_bound(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    persona_id = asyncio.run(
        repo.create(_SAMPLE_CONFIG, locale="en", slug="pre_runtime_persona")
    )
    cache_slugs: list[str] = []

    def fake_set_current_personality(slug, *, config=None):
        _ = config
        cache_slugs.append(slug)

    monkeypatch.setattr(personas_module, "_get_repo", lambda: repo)
    monkeypatch.setattr(
        "magi.personality.active_persona.set_current_personality",
        fake_set_current_personality,
    )
    monkeypatch.setattr(
        "magi.core.runtime_bindings.get_optional_agent_runtime",
        lambda: None,
    )
    client = _build_client(repo, monkeypatch)

    response = client.put("/api/personas/active", json={"persona_id": persona_id})

    assert response.status_code == 200
    assert response.json()["persona_id"] == persona_id
    assert asyncio.run(repo.get_active_id()) == persona_id
    assert cache_slugs == ["pre_runtime_persona"]


@pytest.mark.asyncio
async def test_cancelled_active_switch_restores_previous_persona(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    await repo.init()
    previous_id = await repo.create(
        _SAMPLE_CONFIG,
        locale="en",
        slug="previous_cancel_persona",
    )
    target_config = json.loads(_SAMPLE_CONFIG)
    target_config["name"] = "Cancelled Target"
    target_id = await repo.create(
        json.dumps(target_config),
        locale="en",
        slug="cancelled_target_persona",
    )
    await repo.set_active(previous_id)

    reload_started = asyncio.Event()
    global_slugs: list[str] = []
    memory_slugs: list[str] = []

    def fake_set_current_personality(slug, *, config=None):
        _ = config
        global_slugs.append(slug)

    class _FakeMemory:
        async def reload_personality(self, slug, *, personality_config=None):
            _ = personality_config
            if slug == "cancelled_target_persona":
                reload_started.set()
                await asyncio.Event().wait()
            memory_slugs.append(slug)

    class _FakeManager:
        async def ensure_agent(self, task_agent_type, agent_id):
            _ = (task_agent_type, agent_id)
            return SimpleNamespace(memory=_FakeMemory())

    class _FakeRuntime:
        def get_task_agent_manager(self):
            return _FakeManager()

    monkeypatch.setattr(personas_module, "_get_repo", lambda: repo)
    monkeypatch.setattr(
        "magi.personality.active_persona.set_current_personality",
        fake_set_current_personality,
    )
    monkeypatch.setattr(
        "magi.core.runtime_bindings.get_optional_agent_runtime",
        lambda: _FakeRuntime(),
    )
    request = SimpleNamespace(headers={})
    switch_task = asyncio.create_task(
        personas_module.set_active_persona(
            request,
            personas_module.ActivePersonaRequest(persona_id=target_id),
        )
    )
    await reload_started.wait()

    switch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await switch_task

    assert await repo.get_active_id() == previous_id
    assert global_slugs == ["cancelled_target_persona", "previous_cancel_persona"]
    assert memory_slugs == ["previous_cancel_persona"]


@pytest.mark.asyncio
async def test_cancelled_active_switch_after_registry_write_restores_previous_persona(
    tmp_path,
    monkeypatch,
) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    await repo.init()
    previous_id = await repo.create(
        _SAMPLE_CONFIG,
        locale="en",
        slug="previous_registry_persona",
    )
    target_config = json.loads(_SAMPLE_CONFIG)
    target_config["name"] = "Registry Target"
    target_id = await repo.create(
        json.dumps(target_config),
        locale="en",
        slug="registry_target_persona",
    )
    await repo.set_active(previous_id)

    registry_write_finished = asyncio.Event()
    release_registry_write = asyncio.Event()
    cache_slugs: list[str] = []
    live_memory_slug = "previous_registry_persona"
    original_set_active = repo.set_active

    async def blocking_set_active(persona_id: str) -> None:
        await original_set_active(persona_id)
        if persona_id == target_id:
            registry_write_finished.set()
            await release_registry_write.wait()

    def fake_set_current_personality(slug, *, config=None):
        _ = config
        cache_slugs.append(slug)

    class _FakeMemory:
        async def reload_personality(self, slug, *, personality_config=None):
            nonlocal live_memory_slug
            _ = personality_config
            live_memory_slug = slug

    class _FakeManager:
        async def ensure_agent(self, task_agent_type, agent_id):
            _ = (task_agent_type, agent_id)
            return SimpleNamespace(memory=_FakeMemory())

    class _FakeRuntime:
        def get_task_agent_manager(self):
            return _FakeManager()

    monkeypatch.setattr(repo, "set_active", blocking_set_active)
    monkeypatch.setattr(personas_module, "_get_repo", lambda: repo)
    monkeypatch.setattr(
        "magi.personality.active_persona.set_current_personality",
        fake_set_current_personality,
    )
    monkeypatch.setattr(
        "magi.core.runtime_bindings.get_optional_agent_runtime",
        lambda: _FakeRuntime(),
    )
    request = SimpleNamespace(headers={})
    switch_task = asyncio.create_task(
        personas_module.set_active_persona(
            request,
            personas_module.ActivePersonaRequest(persona_id=target_id),
        )
    )
    await registry_write_finished.wait()

    switch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await switch_task

    assert await repo.get_active_id() == previous_id
    assert cache_slugs == ["previous_registry_persona"]
    assert live_memory_slug == "previous_registry_persona"


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


def test_create_persona_with_same_id_is_idempotent(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    client = _build_client(repo, monkeypatch)
    persona_id = str(uuid.uuid4())
    payload = {
        "persona_id": persona_id,
        "config_json": _SAMPLE_CONFIG,
        "locale": "en",
        "slug": "onboarding-custom-stable",
    }

    first_response = client.post("/api/personas/", json=payload)
    repeated_response = client.post("/api/personas/", json=payload)

    assert first_response.status_code == 201
    assert repeated_response.status_code == 201
    assert first_response.json()["data"]["persona_id"] == persona_id
    assert repeated_response.json()["data"]["persona_id"] == persona_id
    assert asyncio.run(repo.count()) == 1


def test_delete_active_persona_returns_localized_conflict(tmp_path, monkeypatch) -> None:
    repo = PersonaRepository(str(tmp_path / "persona_registry.db"))
    asyncio.run(repo.init())
    persona_id = asyncio.run(repo.create(_SAMPLE_CONFIG, locale="en", slug="active_persona"))
    asyncio.run(repo.set_active(persona_id))
    client = _build_client(repo, monkeypatch)

    response = client.delete(f"/api/personas/{persona_id}", headers={"Accept-Language": "zh-CN"})

    assert response.status_code == 409
    assert response.json()["detail"] == "不能删除当前启用的人格"
