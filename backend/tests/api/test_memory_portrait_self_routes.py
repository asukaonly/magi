"""Integration tests for /api/memory/portrait/self."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.portrait_self_routes import (
    build_router,
    override_dependencies_for_test,
)


def _app():
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/memory")
    return app


def test_cold_start_when_no_projection_and_no_snapshot():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    # Real method: list_tom_snapshots(entity_id=..., limit=1) -> List[Dict]
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    # Real method: list_tom_assertions(entity_id=..., limit=..., offset=...) -> List[Dict]
    l2.list_tom_assertions = AsyncMock(return_value=[])
    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_cold_start"] is True
    assert body["cold_start_reason"] == "no_observations"
    assert body["observations"] == []
    assert body["session_id"] == ""


def test_returns_observations_from_projection_and_snapshot():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=MagicMock(
        user_id="u1",
        display_name="Asuka",
        preferred_form_of_address="阿明",
        real_name="",
        home_location="杭州",
        communication={"response_style.preferred": "concise"},
        identity={},
        preferences={"music.genre": "ambient"},
        state={"focus_mode": "deep_work"},
        completeness_score=0.4,
        refreshed_at=100.0,
    ))
    l2 = MagicMock()
    # list_tom_snapshots returns a list; we return one snapshot dict
    # core_traits is a dict in the real schema (JSON-decoded)
    l2.list_tom_snapshots = AsyncMock(return_value=[{
        "snapshot_id": "snap-1",
        "entity_id": "user:u1",
        "entity_type": "user",
        "core_traits": {"curiosity": "高度好奇、专注、对工程细节敏感"},
        "preferences": {},
        "last_updated_at": 200.0,
    }])
    l2.list_tom_assertions = AsyncMock(return_value=[])
    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_cold_start"] is False
    kinds = [obs["kind"] for obs in body["observations"]]
    assert "assertion" in kinds  # from projection
    assert "reflection" in kinds  # from tom snapshot
    texts = " ".join(obs["text"] for obs in body["observations"])
    assert "杭州" in texts or "阿明" in texts


def test_assertion_observations_include_grouping_metadata_refs():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[{
        "assertion_id": "assert-1",
        "trait_family": "preference_profile",
        "trait_name": "current_project",
        "trait_value": "Magi 记忆体验",
        "validation_state": "tentative",
        "source_domain": "conversation",
    }])
    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    body = resp.json()
    refs = body["observations"][0]["basis_refs"]
    assert "assertion:assert-1" in refs
    assert "family:preference_profile" in refs
    assert "status:tentative" in refs
    assert "source:conversation" in refs
