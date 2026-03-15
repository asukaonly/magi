from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory import memory_router


class _FakeL0Store:
    checkpoint_db_path = "/tmp/l0.db"
    _sessions: dict = {}
    _goal_stack: dict = {}
    _active_entities: dict = {}
    _temporary_tactics: dict = {}


class _FakeL1Store:
    db_path = "/tmp/l1.db"

    async def count_events(self):
        return 12


class _FakeL2Store:
    db_path = "/tmp/l2.db"

    async def get_relationships(self, limit: int = 100):
        return []

    async def list_tom_assertions(self, limit: int = 100):
        return []


class _FakeL3Store:
    db_path = "/tmp/l3.db"

    async def list_summaries(self, limit: int = 100):
        return []


class _FakeL4Store:
    db_path = "/tmp/l4.db"

    async def get_all_skills(self, limit: int = 100):
        _ = limit
        return [
            {
                "skill_id": "skill-1",
                "skill_name": "browser.open",
                "skill_category": "tool",
                "success_rate": 0.75,
                "total_attempts": 8,
                "circuit_breaker_state": "closed",
            }
        ]


class _FakeUnifiedMemory:
    def __init__(self):
        self.l0 = _FakeL0Store()
        self.l1 = _FakeL1Store()
        self.l2 = _FakeL2Store()
        self.l3 = _FakeL3Store()
        self.l4 = _FakeL4Store()

    async def get_statistics(self):
        return {
            "l0": {"checkpoint_db_path": "/tmp/l0.db"},
            "l1": {"event_count": 12},
            "l2": {"db_path": "/tmp/l2.db"},
            "l3": {"db_path": "/tmp/l3.db"},
            "l4": {"db_path": "/tmp/l4.db"},
        }


def test_memory_statistics_api_reports_new_layers(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory.get_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory.get_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/statistics")

    assert response.status_code == 200
    body = response.json()
    assert body["l1"]["event_count"] == 12
    assert "l4" in body


def test_memory_procedures_api_lists_skills(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory.get_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory.get_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/procedures")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["skill_name"] == "browser.open"
    assert body[0]["success_rate"] == 0.75
