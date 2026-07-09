"""Tests for portrait refresh scheduling after L2 assertion feedback routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.router import memory_router

class _FeedbackL2:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.feedback = []

    async def apply_user_feedback(self, *, assertion_id: str, feedback: str):
        self.feedback.append((assertion_id, feedback))
        return {
            "assertion_id": assertion_id,
            "entity_id": "user:local_user",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "interest.magi_memory",
            "trait_value": "Magi 记忆系统",
            "validation_state": "stable",
            "source_domain": "conversation",
            "updated_at": 200.0,
        }

    async def list_tom_assertions(self, **kwargs):
        return [{
            "assertion_id": "assert-1",
            "entity_id": "user:local_user",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "interest.magi_memory",
            "trait_value": "Magi 记忆系统",
            "validation_state": "stable",
            "source_domain": "conversation",
            "evidence_count": 2,
            "updated_at": 200.0,
        }]

    async def list_tom_snapshots(self, **kwargs):
        return []

    async def get_relationships(self, **kwargs):
        return []


class _UnifiedMemory:
    def __init__(self, db_path: str):
        self.l2 = _FeedbackL2(db_path)


def _app():
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")
    return app


async def test_feedback_route_schedules_user_portrait_projection_refresh(
    tmp_path: Path,
    monkeypatch,
):
    db_path = str(tmp_path / "memory.db")
    unified = _UnifiedMemory(db_path)
    scheduled = []

    async def schedule_refresh(unified_memory, assertion):
        scheduled.append((unified_memory, assertion))

    monkeypatch.setattr(
        "magi.api.routers.memory.l2.knowledge_routes._resolve_unified_memory",
        lambda: unified,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.knowledge_routes.schedule_portrait_projection_refresh_after_assertion_change",
        schedule_refresh,
    )

    client = TestClient(_app())
    resp = client.patch(
        "/api/memory/l2/assertions/assert-1/feedback",
        json={"feedback": "confirmed"},
    )

    assert resp.status_code == 200
    assert len(scheduled) == 1
    assert scheduled[0][0] is unified
    assert scheduled[0][1]["entity_id"] == "user:local_user"
