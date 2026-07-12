"""Integration tests for /api/memory/portrait/self."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.portrait_self_routes import (
    build_router,
    override_dependencies_for_test,
)
from magi.user_profile.models import UserPortraitProjection, UserProfileProjection
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder


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


def test_returns_existing_portrait_projection_page_model():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=UserPortraitProjection(
        user_id="u1",
        entity_id="user:u1",
        world={"total_count": 1, "groups": [{"id": "preferences", "items": [{"text": "Magi 记忆系统"}]}]},
        review={"items": []},
        recent={"items": [{"text": "正在验证画像"}]},
        prompt_summary=["用户关注 Magi 记忆系统。"],
    ))
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.get_relationships = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[])

    with override_dependencies_for_test(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["self_view"]["world"]["groups"][0]["items"][0]["text"] == "Magi 记忆系统"
    assert body["self_view"]["recent"]["items"][0]["text"] == "正在验证画像"
    assert body["prompt_summary"] == ["用户关注 Magi 记忆系统。"]


def test_rebuilds_stale_portrait_projection_when_newer_assertion_exists():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=UserPortraitProjection(
        user_id="u1",
        entity_id="user:u1",
        world={"total_count": 1, "groups": [{"id": "preferences", "items": [{"text": "旧画像"}]}]},
        review={"items": []},
        recent={"items": []},
        prompt_summary=["旧画像。"],
        generated_at=100.0,
    ))
    portrait_repo.upsert = AsyncMock(side_effect=lambda projection: projection)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.get_relationships = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[{
        "assertion_id": "assert-new",
        "trait_family": "preference_profile",
        "trait_name": "interest.memory_system",
        "trait_value": "新画像",
        "validation_state": "stable",
        "source_domain": "conversation",
        "evidence_count": 3,
        "updated_at": 200.0,
    }])

    with override_dependencies_for_test(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    body = resp.json()
    preferences = {
        group["id"]: group["items"]
        for group in body["self_view"]["world"]["groups"]
    }["preferences"]
    assert [item["text"] for item in preferences] == ["新画像"]
    assert "旧画像" not in str(body["self_view"])
    portrait_repo.upsert.assert_awaited_once()


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
        "projects",
        "preferences",
        "work_style",
    ]
    assert [item["text"] for item in world_groups["identity"]] == ["希望称呼为「Asuka」"]
    assert [item["text"] for item in world_groups["preferences"]] == ["Magi 记忆系统"]
    assert [item["text"] for item in world_groups["work_style"]] == ["直接给结论"]

    review_items = view["review"]["items"]
    assert [item["text"] for item in review_items] == ["画像页面"]
    assert review_items[0]["assertion_id"] == "assert-review"
    assert review_items[0]["source_key"] == "conversation"

    recent_items = view["recent"]["items"]
    assert [item["text"] for item in recent_items] == [
        "最近在验证关于你页面",
        "检查 L2 结果",
    ]
    assert view["world"]["total_count"] == 3


def test_self_view_keeps_inventory_assertions_out_of_world():
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
    work_style_items = {
        group["id"]: group["items"]
        for group in resp.json()["self_view"]["world"]["groups"]
    }["work_style"]

    assert work_style_items == []
    observations_text = "\n".join(
        item["text"] for item in resp.json()["observations"]
    )
    assert "Codex" not in observations_text
    assert "Docker" not in observations_text


def test_self_view_skips_non_world_ready_passive_assertions():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.get_relationships = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[
        {
            "assertion_id": "assert-weak",
            "trait_family": "preference_profile",
            "trait_name": "interest.deepseek",
            "trait_value": "DeepSeek",
            "validation_state": "stable",
            "source_domain": "external_activity",
            "evidence_count": 1,
        },
        {
            "assertion_id": "assert-mismatch",
            "trait_family": "preference_profile",
            "trait_name": "tool.chrome",
            "trait_value": "Chrome",
            "validation_state": "stable",
            "source_domain": "external_activity",
            "evidence_count": 5,
        },
        {
            "assertion_id": "assert-rag",
            "trait_family": "preference_profile",
            "trait_name": "interest.rag",
            "trait_value": "RAG",
            "validation_state": "stable",
            "source_domain": "external_activity",
            "evidence_count": 3,
        },
    ])

    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    body = resp.json()
    world_groups = {group["id"]: group["items"] for group in body["self_view"]["world"]["groups"]}
    preferences = [item["text"] for item in world_groups["preferences"]]
    observations_text = "\n".join(item["text"] for item in body["observations"])

    assert preferences == ["RAG"]
    assert "DeepSeek" not in observations_text
    assert "Chrome" not in observations_text


def test_self_view_applies_assertion_limit_after_signal_filtering():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.get_relationships = AsyncMock(return_value=[])
    weak_items = [
        {
            "assertion_id": f"assert-weak-{index}",
            "trait_family": "preference_profile",
            "trait_name": f"interest.weak_{index}",
            "trait_value": f"Weak {index}",
            "validation_state": "stable",
            "source_domain": "external_activity",
            "evidence_count": 1,
        }
        for index in range(20)
    ]
    l2.list_tom_assertions = AsyncMock(return_value=[
        *weak_items,
        {
            "assertion_id": "assert-rag",
            "trait_family": "preference_profile",
            "trait_name": "interest.rag",
            "trait_value": "RAG",
            "validation_state": "stable",
            "source_domain": "external_activity",
            "evidence_count": 3,
        },
    ])

    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    world_groups = {group["id"]: group["items"] for group in resp.json()["self_view"]["world"]["groups"]}
    assert [item["text"] for item in world_groups["preferences"]] == ["RAG"]


def test_self_view_keeps_inventory_graph_relationships_out_of_world():
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

    assert all(not items for items in world_groups.values())
    assert body["self_view"]["recent"]["items"] == []


def test_self_view_skips_photo_place_inventory_signals():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[])
    l2.get_relationships = AsyncMock(return_value=[
        {
            "triple_id": "triple-coord",
            "predicate": "VISITED",
            "object_id": "place:30.1234, 120.5678",
            "object_type": "place",
            "source_type": "photo_library_apple_photos",
            "observation_count": 4,
        },
        {
            "triple_id": "triple-place",
            "predicate": "VISITED",
            "object_id": "place:杭州",
            "object_type": "place",
            "source_type": "photo_library_apple_photos",
            "observation_count": 4,
        },
    ])

    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    self_view = resp.json()["self_view"]
    world_groups = {group["id"]: group["items"] for group in self_view["world"]["groups"]}
    assert all(not items for items in world_groups.values())
    assert self_view["recent"]["items"] == []


def test_self_view_fallback_uses_converged_portrait_projection_with_profile_input():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=UserProfileProjection(
        user_id="u1",
        entity_id="user:u1",
        display_name="子涵",
        preferred_form_of_address="子涵",
        home_location="杭州",
    ))
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.list_tom_snapshots = AsyncMock(return_value=[])
    l2.get_relationships = AsyncMock(return_value=[])
    l2.list_tom_assertions = AsyncMock(return_value=[
        {
            "assertion_id": "a-project",
            "trait_family": "routine_profile",
            "trait_name": "project.magi_memory",
            "trait_value": "Magi 记忆系统",
            "validation_state": "stable",
            "source_domain": "conversation",
            "evidence_count": 3,
        },
        {
            "assertion_id": "a-interest",
            "trait_family": "preference_profile",
            "trait_name": "interest.plugin_ecosystem",
            "trait_value": "插件生态",
            "validation_state": "stable",
            "source_domain": "conversation",
            "evidence_count": 2,
        },
        {
            "assertion_id": "a-communication",
            "trait_family": "communication_profile",
            "trait_name": "communication.answer_style",
            "trait_value": "先讲结论",
            "validation_state": "stable",
            "source_domain": "user_authored",
            "evidence_count": 1,
        },
    ])

    with override_dependencies_for_test(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})

    assert resp.status_code == 200
    body = resp.json()
    world_groups = {group["id"]: group for group in body["self_view"]["world"]["groups"]}
    assert [group["id"] for group in body["self_view"]["world"]["groups"]] == [
        "identity",
        "projects",
        "preferences",
        "work_style",
    ]
    assert "子涵" in world_groups["identity"]["summary"]
    assert "杭州" in world_groups["identity"]["summary"]
    assert "Magi 记忆系统" in world_groups["projects"]["summary"]
    assert "插件生态" in world_groups["preferences"]["summary"]
    assert "先讲结论" in world_groups["work_style"]["summary"]
    assert body["prompt_summary"]
    assert "external_activity" not in "\n".join(body["prompt_summary"])


class _ConsistencyL2:
    """L2 fake usable by both the builder and the route fallback path.

    Exposes only assertions plus empty snapshots and intentionally omits
    ``get_relationships`` so the route fallback skips graph observations. This
    isolates the comparison to assertion-derived world/review/recent
    classification, which is exactly what the shared qualification policy owns.
    """

    def __init__(self, assertions: list[dict]):
        self._assertions = assertions

    async def list_tom_assertions(self, **kwargs):
        return [dict(item) for item in self._assertions]

    async def list_tom_snapshots(self, **kwargs):
        return []


def _world_buckets(world: dict) -> dict[str, list[str]]:
    return {
        group["id"]: sorted(item["text"] for item in group["items"])
        for group in world["groups"]
    }


def test_materialized_and_fallback_portrait_classify_assertions_identically():
    """The materialized projection and the API fallback must bucket the same
    assertions into identical world/review/recent groups (single qualification
    policy). This guards against the two paths drifting apart again."""
    assertions = [
        {  # world / preferences (explicit source)
            "assertion_id": "a-pref",
            "trait_family": "preference_profile",
            "trait_name": "interest.magi_memory",
            "trait_value": "Magi 记忆系统",
            "validation_state": "stable",
            "source_domain": "conversation",
            "evidence_count": 3,
        },
        {  # world / work style
            "assertion_id": "a-routine",
            "trait_family": "routine_profile",
            "trait_name": "tool",
            "trait_value": "本地插件仓库",
            "validation_state": "stable",
            "source_domain": "user_authored",
            "evidence_count": 2,
        },
        {  # world / work style
            "assertion_id": "a-comm",
            "trait_family": "communication_profile",
            "trait_name": "communication.answer_style",
            "trait_value": "先讲结论",
            "validation_state": "stable",
            "source_domain": "user_authored",
            "evidence_count": 1,
        },
        {  # review (tentative)
            "assertion_id": "a-review",
            "trait_family": "preference_profile",
            "trait_name": "interest.one_off",
            "trait_value": "一次性页面",
            "validation_state": "tentative",
            "source_domain": "external_activity",
            "evidence_count": 1,
        },
        {  # recent (state family)
            "assertion_id": "a-recent",
            "trait_family": "state_profile",
            "trait_name": "current_focus",
            "trait_value": "验证画像",
            "validation_state": "stable",
            "source_domain": "conversation",
            "evidence_count": 4,
        },
        {  # skip: weak passive interest below evidence floor
            "assertion_id": "a-skip",
            "trait_family": "preference_profile",
            "trait_name": "interest.weak",
            "trait_value": "弱信号",
            "validation_state": "stable",
            "source_domain": "external_activity",
            "evidence_count": 1,
        },
    ]
    l2 = _ConsistencyL2(assertions)

    materialized = asyncio.run(UserPortraitProjectionBuilder(l2).build("u1"))

    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=None)
    with override_dependencies_for_test(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})
    assert resp.status_code == 200
    fallback = resp.json()["self_view"]

    assert _world_buckets(materialized.world) == _world_buckets(fallback["world"])
    assert (
        sorted(item["text"] for item in materialized.review["items"])
        == sorted(item["text"] for item in fallback["review"]["items"])
    )
    assert (
        sorted(item["text"] for item in materialized.recent["items"])
        == sorted(item["text"] for item in fallback["recent"]["items"])
    )

    # Sanity: every role bucket is actually exercised (not vacuously equal).
    assert _world_buckets(fallback["world"]) == {
        "identity": [],
        "projects": [],
        "preferences": ["Magi 记忆系统"],
        "work_style": ["先讲结论"],
    }
    assert sorted(item["text"] for item in fallback["review"]["items"]) == ["一次性页面"]
    assert sorted(item["text"] for item in fallback["recent"]["items"]) == ["验证画像"]


class _ConsistencyGraphL2:
    """L2 fake exposing assertions plus graph relationships for both paths."""

    def __init__(self, assertions: list[dict], relationships: list[dict]):
        self._assertions = assertions
        self._relationships = relationships

    async def list_tom_assertions(self, **kwargs):
        return [dict(item) for item in self._assertions]

    async def list_tom_snapshots(self, **kwargs):
        return []

    async def get_relationships(self, **kwargs):
        return [dict(edge) for edge in self._relationships]


def test_materialized_and_fallback_portrait_include_recent_graph_clues_identically():
    """Qualified graph clues must remain recent on both projection paths."""
    assertions = [
        {
            "assertion_id": "a-routine",
            "trait_family": "routine_profile",
            "trait_name": "tool",
            "trait_value": "本地插件仓库",
            "validation_state": "stable",
            "source_domain": "user_authored",
            "evidence_count": 2,
        },
    ]
    relationships = [
        {
            "triple_id": "t-topic",
            "predicate": "INTERESTED_IN",
            "object_id": "topic:机器学习",
            "object_type": "topic",
            "source_type": "browser_history",
            "observation_count": 3,
        },
        {
            "triple_id": "t-tool",
            "predicate": "WORKS_WITH",
            "object_id": "software:Chrome",
            "object_type": "software",
            "source_type": "chrome_history",
            "observation_count": 5,
        },
    ]
    l2 = _ConsistencyGraphL2(assertions, relationships)

    materialized = asyncio.run(UserPortraitProjectionBuilder(l2).build("u1"))

    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=None)
    with override_dependencies_for_test(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})
    assert resp.status_code == 200
    fallback = resp.json()["self_view"]

    assert _world_buckets(materialized.world) == _world_buckets(fallback["world"])
    assert _world_buckets(fallback["world"]) == {
        "identity": [],
        "projects": [],
        "preferences": [],
        "work_style": [],
    }
    assert sorted(item["text"] for item in fallback["recent"]["items"]) == [
        "Chrome",
        "机器学习",
    ]


class _ConsistencySnapshotL2:
    """L2 fake exposing only a multi-trait ToM snapshot for both paths."""

    def __init__(self, snapshot: dict):
        self._snapshot = snapshot

    async def list_tom_assertions(self, **kwargs):
        return []

    async def list_tom_snapshots(self, **kwargs):
        return [dict(self._snapshot)]


def test_materialized_and_fallback_render_multi_trait_snapshot_identically():
    """A snapshot with multiple core_traits must produce the same per-trait
    recent items on both paths (previously the fallback concatenated them)."""
    snapshot = {
        "snapshot_id": "snap-multi",
        "entity_id": "user:u1",
        "entity_type": "user",
        "core_traits": {"focus": "验证画像", "mood": "专注"},
        "evidence_count": 3,
        "last_updated_at": 200.0,
    }
    l2 = _ConsistencySnapshotL2(snapshot)

    materialized = asyncio.run(UserPortraitProjectionBuilder(l2).build("u1"))

    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=None)
    with override_dependencies_for_test(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})
    assert resp.status_code == 200
    fallback = resp.json()["self_view"]

    materialized_recent = sorted(item["text"] for item in materialized.recent["items"])
    fallback_recent = sorted(item["text"] for item in fallback["recent"]["items"])
    assert materialized_recent == fallback_recent == ["专注", "验证画像"]
