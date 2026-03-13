from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory import memory_router
from magi.memory.l5_capabilities import Capability


class _FakeCapabilityMemory:
    def get_all_capabilities(self):
        return [
            Capability(
                capability_id="cap-test",
                name="Chrome Recall",
                description="Recall recent browser activity",
                category="browser",
                proficiency=0.75,
                usage_count=8,
                success_count=6,
                last_used=1773400000.0,
            )
        ]


class _FakeUnifiedMemory:
    def __init__(self):
        self.l5_capabilities = _FakeCapabilityMemory()


def test_memory_capabilities_api_derives_success_rate(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory.get_unified_memory", lambda: _FakeUnifiedMemory())

    client = TestClient(app)
    response = client.get("/api/memory/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["capability_id"] == "cap-test"
    assert body[0]["success_rate"] == 0.75
    assert body[0]["usage_count"] == 8
