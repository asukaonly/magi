"""Integration tests for /api/memory/portrait/self."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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

    refs_by_text = {obs["text"]: obs["basis_refs"] for obs in body["observations"]}
    assert "family:identity_profile" in refs_by_text["称呼你「阿明」"]
    assert "family:identity_profile" in refs_by_text["住在杭州"]
    assert "family:preference_profile" in refs_by_text["偏好：music.genre = ambient"]
    assert "family:communication_profile" in refs_by_text["沟通风格：response_style.preferred = concise"]
    assert "family:state_profile" in refs_by_text["近期状态：focus_mode = deep_work"]


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


def test_self_view_hides_internal_external_activity_source():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[{
        "assertion_id": "assert-external",
        "trait_family": "preference_profile",
        "trait_name": "interest.codex",
        "trait_value": "Codex",
        "validation_state": "corroborated",
        "source_domain": "external_activity",
        "evidence_count": 4,
    }])

    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    body = resp.json()
    refs = body["observations"][0]["basis_refs"]
    assert "source:external_activity" in refs

    preferences = {
        group["id"]: group["items"]
        for group in body["self_view"]["world"]["groups"]
    }["preferences"]
    assert preferences[0]["text"] == "Codex"
    assert preferences[0]["source"] == ""
    assert preferences[0]["source_key"] is None


def test_self_portrait_returns_backend_grouped_page_model():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=MagicMock(
        user_id="u1",
        display_name="Asuka",
        preferred_form_of_address="Asuka",
        real_name="",
        home_location="",
        communication={"response_style.preferred": "直接给结论"},
        identity={},
        preferences={"topic": "Magi 记忆系统"},
        state={},
        completeness_score=0.4,
        refreshed_at=100.0,
    ))
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[{
        "snapshot_id": "snap-1",
        "entity_id": "user:u1",
        "entity_type": "user",
        "core_traits": {"近期线索": "最近在验证关于你页面"},
        "evidence_count": 3,
        "last_updated_at": 200.0,
    }])
    l2.list_tom_assertions = AsyncMock(return_value=[
        {
            "assertion_id": "assert-routine",
            "trait_family": "routine_profile",
            "trait_name": "tool",
            "trait_value": "本地插件仓库",
            "validation_state": "stable",
            "source_domain": "conversation",
            "evidence_count": 2,
        },
        {
            "assertion_id": "assert-review",
            "trait_family": "preference_profile",
            "trait_name": "current_project",
            "trait_value": "画像页面",
            "validation_state": "tentative",
            "source_domain": "conversation",
            "evidence_count": 1,
        },
        {
            "assertion_id": "assert-recent",
            "trait_family": "state_profile",
            "trait_name": "focus",
            "trait_value": "检查 L2 结果",
            "validation_state": "stable",
            "source_domain": "conversation",
            "evidence_count": 4,
        },
    ])

    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    body = resp.json()
    view = body["self_view"]

    world_groups = {group["id"]: group["items"] for group in view["world"]["groups"]}
    assert [group["id"] for group in view["world"]["groups"]] == [
        "identity",
        "preferences",
        "routine",
        "places",
        "communication",
    ]
    assert [item["text"] for item in world_groups["identity"]] == ["称呼你「Asuka」"]
    assert [item["text"] for item in world_groups["preferences"]] == ["Magi 记忆系统"]
    assert [item["text"] for item in world_groups["routine"]] == ["本地插件仓库"]
    assert [item["text"] for item in world_groups["communication"]] == ["直接给结论"]

    review_items = view["review"]["items"]
    assert [item["text"] for item in review_items] == ["画像页面"]
    assert review_items[0]["assertion_id"] == "assert-review"
    assert review_items[0]["source_key"] == "conversation"

    recent_items = view["recent"]["items"]
    assert [item["text"] for item in recent_items] == [
        "最近在验证关于你页面",
        "检查 L2 结果",
    ]
    assert view["world"]["total_count"] == len(body["observations"])


def test_self_view_dedupes_world_items_and_prioritizes_stronger_profile_signals():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[
        {
            "assertion_id": "assert-low",
            "trait_family": "routine_profile",
            "trait_name": "tool.docker",
            "trait_value": "Docker",
            "validation_state": "corroborated",
            "source_domain": "external_activity",
            "evidence_count": 2,
        },
        {
            "assertion_id": "assert-high",
            "trait_family": "routine_profile",
            "trait_name": "tool.codex",
            "trait_value": "Codex",
            "validation_state": "stable",
            "source_domain": "user_authored",
            "evidence_count": 1,
        },
        {
            "assertion_id": "assert-dup",
            "trait_family": "routine_profile",
            "trait_name": "tool.docker.duplicate",
            "trait_value": "Docker",
            "validation_state": "stable",
            "source_domain": "external_activity",
            "evidence_count": 6,
        },
    ])

    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    routine_items = {
        group["id"]: group["items"]
        for group in resp.json()["self_view"]["world"]["groups"]
    }["routine"]

    assert [item["text"] for item in routine_items] == ["Codex", "Docker"]
    assert routine_items[0]["source_key"] == "user_authored"
    assert routine_items[1]["assertion_id"] == "assert-dup"


def test_self_view_includes_safe_graph_relationship_signals():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[])
    l2.get_relationships = AsyncMock(return_value=[
        {
            "triple_id": "triple-place",
            "predicate": "VISITED",
            "object_id": "place:东京",
            "object_type": "place",
            "source_type": "photo_library_apple_photos",
            "observation_count": 3,
        },
        {
            "triple_id": "triple-camera",
            "predicate": "OWNS",
            "object_id": "hardware:Sony A7C",
            "object_type": "hardware",
            "source_type": "photo_library_apple_photos",
            "observation_count": 4,
        },
        {
            "triple_id": "triple-single",
            "predicate": "VISITED",
            "object_id": "place:一次性地点",
            "object_type": "place",
            "source_type": "photo_library_apple_photos",
            "observation_count": 1,
        },
    ])

    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    body = resp.json()
    world_groups = {group["id"]: group["items"] for group in body["self_view"]["world"]["groups"]}

    assert [item["text"] for item in world_groups["places"]] == ["东京"]
    assert world_groups["places"][0]["source_key"] == "photo_library_apple_photos"
    assert [item["text"] for item in world_groups["routine"]] == ["Sony A7C"]
    assert "一次性地点" not in " ".join(item["text"] for group in world_groups.values() for item in group)
