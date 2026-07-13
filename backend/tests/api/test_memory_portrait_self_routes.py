"""Integration tests for the product-facing self portrait endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.portrait_self_routes import (
    build_router,
    override_dependencies_for_test,
)
from magi.user_profile.models import (
    USER_PORTRAIT_PROJECTION_VERSION,
    UserPortraitProjection,
    UserProfileProjection,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/memory")
    return app


def _get(*, profile_repo=None, portrait_repo=None, l2=None) -> dict:
    with override_dependencies_for_test(
        profile_repo=profile_repo,
        portrait_repo=portrait_repo,
        l2=l2,
    ):
        response = TestClient(_app()).get(
            "/api/memory/portrait/self",
            params={"user_id": "u1"},
        )
    assert response.status_code == 200
    return response.json()


def _empty_l2() -> MagicMock:
    l2 = MagicMock()
    l2.list_tom_assertions = AsyncMock(return_value=[])
    return l2


def _portrait(*, generated_at: float = 200.0, version: int | None = None) -> UserPortraitProjection:
    return UserPortraitProjection(
        user_id="u1",
        entity_id="user:u1",
        version=version or USER_PORTRAIT_PROJECTION_VERSION,
        world={
            "total_count": 1,
            "groups": [
                {
                    "id": "preferences",
                    "summary": "关注或偏好：Magi 记忆系统",
                    "items": [{"id": "a1", "text": "Magi 记忆系统"}],
                }
            ],
        },
        review={"items": []},
        recent={"items": []},
        prompt_summary=["用户关注或偏好：Magi 记忆系统。"],
        generated_at=generated_at,
    )


def test_cold_start_returns_only_empty_grouped_view():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)

    body = _get(profile_repo=profile_repo, l2=_empty_l2())

    assert body["is_cold_start"] is True
    assert body["cold_start_reason"] == "no_understanding"
    assert set(body) == {
        "generated_at",
        "self_view",
        "is_cold_start",
        "cold_start_line",
        "cold_start_reason",
        "is_stale",
    }
    assert [group["id"] for group in body["self_view"]["world"]["groups"]] == [
        "identity",
        "projects",
        "preferences",
        "work_style",
    ]


def test_returns_existing_portrait_projection_without_rebuilding():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=_portrait())
    portrait_repo.upsert = AsyncMock()
    l2 = _empty_l2()

    body = _get(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2)

    assert body["is_cold_start"] is False
    assert body["self_view"]["world"]["groups"][0]["items"][0]["text"] == (
        "Magi 记忆系统"
    )
    portrait_repo.upsert.assert_not_awaited()


def test_rebuilds_portrait_when_newer_assertion_exists():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=_portrait(generated_at=100.0))
    portrait_repo.upsert = AsyncMock(side_effect=lambda projection: projection)
    l2 = MagicMock()
    l2.list_tom_assertions = AsyncMock(
        return_value=[
            {
                "assertion_id": "assert-new",
                "trait_family": "interest_profile",
                "trait_name": "interest.new_portrait",
                "trait_value": "新画像",
                "validation_state": "stable",
                "source_domain": "conversation",
                "temporal_scope": "stable",
                "updated_at": 200.0,
            }
        ]
    )

    body = _get(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2)

    items = {
        group["id"]: group["items"]
        for group in body["self_view"]["world"]["groups"]
    }
    assert [item["text"] for item in items["preferences"]] == ["新画像"]
    portrait_repo.upsert.assert_awaited_once()


def test_rebuilds_portrait_when_projection_version_is_old():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(
        return_value=_portrait(version=USER_PORTRAIT_PROJECTION_VERSION - 1)
    )
    portrait_repo.upsert = AsyncMock(side_effect=lambda projection: projection)

    body = _get(
        profile_repo=profile_repo,
        portrait_repo=portrait_repo,
        l2=_empty_l2(),
    )

    assert body["is_cold_start"] is True
    portrait_repo.upsert.assert_awaited_once()


def test_builds_clean_world_review_and_recent_sections_from_governed_inputs():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(
        return_value=UserProfileProjection(
            user_id="u1",
            entity_id="user:u1",
            preferred_form_of_address="子涵",
        )
    )
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=None)
    portrait_repo.upsert = AsyncMock(side_effect=lambda projection: projection)
    l2 = MagicMock()
    l2.list_tom_assertions = AsyncMock(
        return_value=[
            {
                "assertion_id": "a-project",
                "trait_family": "project_profile",
                "trait_name": "project.magi",
                "trait_value": "Magi 记忆系统",
                "validation_state": "stable",
                "source_domain": "conversation",
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-interest",
                "trait_family": "interest_profile",
                "trait_name": "interest.diiv",
                "trait_value": "DIIV",
                "validation_state": "stable",
                "source_domain": "external_activity",
                "temporal_scope": "recent",
            },
            {
                "assertion_id": "a-review",
                "trait_family": "communication_profile",
                "trait_name": "communication.answer_style",
                "trait_value": "先讲结论",
                "validation_state": "tentative",
                "source_domain": "conversation",
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-inventory",
                "trait_family": "routine_profile",
                "trait_name": "routine.tool.chrome",
                "trait_value": "Chrome",
                "validation_state": "stable",
                "source_domain": "external_activity",
                "temporal_scope": "stable",
            },
        ]
    )

    body = _get(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2)
    view = body["self_view"]
    world = {group["id"]: group for group in view["world"]["groups"]}

    assert "子涵" in world["identity"]["summary"]
    assert [item["text"] for item in world["projects"]["items"]] == ["Magi 记忆系统"]
    assert [item["text"] for item in view["recent"]["items"]] == ["DIIV"]
    assert view["recent"]["items"][0]["claim_kind"] == "preference_interest"
    assert view["recent"]["items"][0]["source"] == ""
    assert [item["text"] for item in view["review"]["items"]] == ["先讲结论"]
    assert "Chrome" not in str(view)


def test_raw_graph_and_snapshot_data_are_not_queried_by_portrait_route():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = _empty_l2()
    l2.get_relationships = AsyncMock(side_effect=AssertionError("graph must not be read"))
    l2.list_tom_snapshots = AsyncMock(side_effect=AssertionError("snapshot must not be read"))

    body = _get(profile_repo=profile_repo, l2=l2)

    assert body["is_cold_start"] is True
    l2.get_relationships.assert_not_awaited()
    l2.list_tom_snapshots.assert_not_awaited()


def test_returns_rebuilt_projection_when_cache_write_fails():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    portrait_repo = MagicMock()
    portrait_repo.get = AsyncMock(return_value=None)
    portrait_repo.upsert = AsyncMock(side_effect=RuntimeError("disk unavailable"))
    l2 = MagicMock()
    l2.list_tom_assertions = AsyncMock(
        return_value=[
            {
                "assertion_id": "a1",
                "trait_family": "interest_profile",
                "trait_name": "interest.diiv",
                "trait_value": "DIIV",
                "validation_state": "stable",
                "source_domain": "conversation",
                "temporal_scope": "stable",
            }
        ]
    )

    body = _get(profile_repo=profile_repo, portrait_repo=portrait_repo, l2=l2)

    assert body["is_cold_start"] is False
    assert "DIIV" in str(body["self_view"])
