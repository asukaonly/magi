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
        "persona_entity": {
            "basic_profile": {
                "name": "Trace Persona",
                "description": "Persona used by active switch characterization.",
                "avatar": "trace.jpg",
            }
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
    monkeypatch.setattr("magi.personality.current_state.set_current_personality", fake_set_current_personality)
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", lambda: _FakeRuntime())

    app = FastAPI()
    app.include_router(personas_router, prefix="/api/personas")

    response = TestClient(app).put("/api/personas/active", json={"persona_id": persona_id})

    assert response.status_code == 200
    assert response.json()["persona_id"] == persona_id
    assert asyncio.run(repo.get_active_id()) == persona_id
    assert state_calls == [("trace_persona", "Trace Persona")]
    assert reload_calls == [("trace_persona", "Trace Persona")]
