"""Integration tests for /memory/l2/experiences surface."""

from __future__ import annotations

import asyncio
import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory.router import memory_router


@pytest.fixture
def public_app_with_mock_memory():
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
        prefix="/api/memory",
    )

    def _build(unified_memory):
        return patch(
            "magi.api.routers.memory.l2.experiences_routes._resolve_unified_memory",
            return_value=unified_memory,
        )

    return app, _build


def test_experience_routes_are_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    routes = {
        (route.path, tuple(sorted(route.methods or [])))
        for route in public.routes
        if getattr(route, "path", "").startswith("/l2/experience")
    }

    assert ("/l2/experiences", ("GET",)) in routes
    assert ("/l2/experiences/{experience_id}", ("GET",)) in routes
    assert ("/l2/experiences/{experience_id}", ("PATCH",)) in routes
    assert ("/l2/experiences/{experience_id}/hide", ("POST",)) in routes
    assert ("/l2/experiences/{experience_id}/regenerate", ("POST",)) in routes
    assert ("/l2/experience-seeds", ("GET",)) in routes
    assert ("/l2/experience-seeds", ("POST",)) in routes
    assert ("/l2/experience-seeds/{seed_id}/promote", ("POST",)) in routes
    assert ("/l2/experience-seeds/{seed_id}/reject", ("POST",)) in routes
    assert ("/l2/experience-drafts/organize", ("POST",)) in routes
    assert ("/l2/experience-drafts", ("GET",)) in routes
    assert ("/l2/experience-drafts/{draft_id}", ("GET",)) in routes
    assert ("/l2/experience-drafts/{draft_id}", ("PATCH",)) in routes
    assert ("/l2/experience-drafts/{draft_id}/cover", ("POST",)) in routes
    assert ("/l2/experience-drafts/{draft_id}/create", ("POST",)) in routes


def test_organize_experience_draft_returns_persisted_draft(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    unified = MagicMock()

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.organize_experience_draft",
            new=AsyncMock(
                return_value={
                    "status": "draft",
                    "draft": {
                        "draft_id": "draft-japan",
                        "status": "editing",
                        "query_text": "2026年5月1日到10日 日本旅行",
                        "title": "日本旅行",
                        "one_sentence_review": "从东京到京都的一段旅行。",
                        "time_start": 100.0,
                        "time_end": 500.0,
                        "chapters": [],
                        "possible_evidence": [],
                        "excluded_evidence": [],
                        "created_experience_id": None,
                        "created_at": 1.0,
                        "updated_at": 1.0,
                    },
                    "choices": [],
                    "message": None,
                }
            ),
        ) as organize,
    ):
        response = TestClient(app).post(
            "/api/memory/l2/experience-drafts/organize",
            json={"query_text": "2026年5月1日到10日 日本旅行"},
        )

    assert response.status_code == 200
    assert response.json()["draft"]["draft_id"] == "draft-japan"
    organize.assert_awaited_once_with(
        unified,
        query_text="2026年5月1日到10日 日本旅行",
        time_start=None,
        time_end=None,
    )


def test_get_experience_draft_batches_distinct_counts_and_persists_them_once(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    stored_draft = {
        "draft_id": "draft-japan",
        "status": "editing",
        "title": "日本旅行",
        "updated_at": 10.0,
        "chapters": [
            {
                "chapter_id": "chapter-route",
                "episode_ids": ["ep-shared", "ep-train"],
                "event_ids": ["evt-direct", "evt-shared"],
            },
            {
                "chapter_id": "chapter-lodging",
                "episode_ids": ["ep-shared", "ep-lodging"],
                "event_ids": [],
            },
        ],
        "possible_evidence": [
            {
                "ref_type": "episode",
                "ref_id": "ep-possible",
                "title": "可能相关",
                "summary": "另一段来源片段。",
            }
        ],
        "excluded_evidence": [
            {
                "ref_type": "event",
                "ref_id": "evt-excluded",
                "title": "已排除事件",
                "summary": "不属于这段经历。",
            }
        ],
    }
    l2.get_experience_draft = AsyncMock(side_effect=lambda **_: copy.deepcopy(stored_draft))

    async def update_experience_draft(**updates):
        assert updates["expected_updated_at"] == 10.0
        stored_draft.update(
            copy.deepcopy(
                {
                    key: value
                    for key, value in updates.items()
                    if key not in {"draft_id", "expected_updated_at"}
                }
            )
        )
        return True

    l2.update_experience_draft = AsyncMock(side_effect=update_experience_draft)
    active_fetches = 0
    max_active_fetches = 0

    async def list_episode_events(*, episode_id: str, limit: int):
        nonlocal active_fetches, max_active_fetches
        assert limit == 10_000
        active_fetches += 1
        max_active_fetches = max(max_active_fetches, active_fetches)
        await asyncio.sleep(0.01)
        active_fetches -= 1
        memberships = {
            "ep-shared": [
                {"event_id": "evt-shared"},
                {"event_id": "evt-shared"},
            ],
            "ep-train": [
                {"event_id": "evt-train"},
            ],
            "ep-lodging": [
                {"event_id": "evt-lodging"},
            ],
            "ep-possible": [
                {"event_id": "evt-possible"},
                {"event_id": "evt-possible"},
            ],
        }
        return memberships[episode_id]

    l2.list_episode_events = AsyncMock(side_effect=list_episode_events)
    unified = MagicMock(l2=l2)

    with build_patcher(unified):
        first_response = TestClient(app).get(
            "/api/memory/l2/experience-drafts/draft-japan",
        )
        second_response = TestClient(app).get(
            "/api/memory/l2/experience-drafts/draft-japan",
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    payload = first_response.json()
    assert payload["chapters"][0]["event_count"] == 3
    assert payload["chapters"][1]["event_count"] == 2
    assert payload["possible_evidence"][0]["event_count"] == 1
    assert payload["excluded_evidence"][0]["event_count"] == 1
    assert second_response.json() == payload
    assert max_active_fetches > 1
    fetched_episode_ids = [
        call.kwargs["episode_id"] for call in l2.list_episode_events.await_args_list
    ]
    assert sorted(fetched_episode_ids) == sorted(
        [
            "ep-shared",
            "ep-train",
            "ep-lodging",
            "ep-possible",
        ]
    )
    assert len(fetched_episode_ids) == len(set(fetched_episode_ids))
    l2.update_experience_draft.assert_awaited_once_with(
        draft_id="draft-japan",
        expected_updated_at=10.0,
        chapters=payload["chapters"],
        possible_evidence=payload["possible_evidence"],
        excluded_evidence=payload["excluded_evidence"],
    )


def test_get_experience_draft_keeps_episode_counts_unknown_without_membership_capability(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    draft = {
        "draft_id": "draft-unknown",
        "status": "editing",
        "title": "Unknown membership",
        "updated_at": 3.0,
        "chapters": [
            {
                "chapter_id": "chapter-episode",
                "episode_ids": ["ep-unknown"],
                "event_ids": ["evt-direct"],
            }
        ],
        "possible_evidence": [
            {
                "ref_type": "event",
                "ref_id": "evt-possible",
                "title": "Direct event",
                "summary": "Explicit evidence.",
            }
        ],
        "excluded_evidence": [
            {
                "ref_type": "unsupported",
                "ref_id": "unknown-ref",
                "title": "Unknown evidence",
                "summary": "No count capability exists.",
            }
        ],
    }
    l2 = MagicMock()
    l2.get_experience_draft = AsyncMock(return_value=copy.deepcopy(draft))
    l2.update_experience_draft = AsyncMock(return_value=True)

    with build_patcher(MagicMock(l2=l2)):
        response = TestClient(app).get(
            "/api/memory/l2/experience-drafts/draft-unknown",
        )

    assert response.status_code == 200
    payload = response.json()
    assert "event_count" not in payload["chapters"][0]
    assert payload["possible_evidence"][0]["event_count"] == 1
    assert "event_count" not in payload["excluded_evidence"][0]
    persisted = l2.update_experience_draft.await_args.kwargs
    assert "chapters" not in persisted
    assert persisted["possible_evidence"][0]["event_count"] == 1


def test_get_experience_draft_returns_hydrated_counts_when_persistence_fails(
    public_app_with_mock_memory,
):
    from magi.api.routers.memory.l2 import experiences_routes

    app, build_patcher = public_app_with_mock_memory
    draft = {
        "draft_id": "draft-write-fails",
        "status": "editing",
        "title": "Readable draft",
        "updated_at": 4.0,
        "chapters": [
            {
                "chapter_id": "chapter-1",
                "episode_ids": ["ep-1"],
                "event_ids": [],
            }
        ],
        "possible_evidence": [],
        "excluded_evidence": [],
    }
    l2 = MagicMock()
    l2.get_experience_draft = AsyncMock(return_value=copy.deepcopy(draft))
    l2.list_episode_events = AsyncMock(return_value=[{"event_id": "evt-1"}])
    l2.update_experience_draft = AsyncMock(side_effect=RuntimeError("disk unavailable"))

    with (
        build_patcher(MagicMock(l2=l2)),
        patch.object(experiences_routes, "logger", create=True) as logger,
    ):
        response = TestClient(app, raise_server_exceptions=False).get(
            "/api/memory/l2/experience-drafts/draft-write-fails",
        )

    assert response.status_code == 200
    assert response.json()["chapters"][0]["event_count"] == 1
    warning = logger.warning
    warning.assert_called_once()
    assert warning.call_args.args[0] == "experience_draft_count_backfill_failed"
    assert warning.call_args.kwargs["draft_id"] == "draft-write-fails"


def test_get_experience_draft_skips_count_persistence_after_concurrent_update(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    initial = {
        "draft_id": "draft-concurrent",
        "status": "editing",
        "title": "Initial title",
        "updated_at": 5.0,
        "chapters": [
            {
                "chapter_id": "chapter-1",
                "episode_ids": ["ep-1"],
                "event_ids": [],
            }
        ],
        "possible_evidence": [],
        "excluded_evidence": [],
    }
    concurrent = {**initial, "title": "Newer title", "updated_at": 6.0}
    l2 = MagicMock()
    l2.get_experience_draft = AsyncMock(
        side_effect=[
            copy.deepcopy(initial),
            copy.deepcopy(concurrent),
        ]
    )
    l2.list_episode_events = AsyncMock(return_value=[{"event_id": "evt-1"}])
    l2.update_experience_draft = AsyncMock(return_value=True)

    with build_patcher(MagicMock(l2=l2)):
        response = TestClient(app).get(
            "/api/memory/l2/experience-drafts/draft-concurrent",
        )

    assert response.status_code == 200
    assert response.json()["chapters"][0]["event_count"] == 1
    l2.update_experience_draft.assert_not_awaited()


def test_get_experience_draft_bounds_membership_read_concurrency(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    episode_ids = [f"ep-{index}" for index in range(30)]
    draft = {
        "draft_id": "draft-large",
        "status": "editing",
        "title": "Large draft",
        "updated_at": 7.0,
        "chapters": [
            {
                "chapter_id": "chapter-large",
                "episode_ids": episode_ids,
                "event_ids": [],
            }
        ],
        "possible_evidence": [],
        "excluded_evidence": [],
    }
    active_reads = 0
    max_active_reads = 0

    async def list_episode_events(*, episode_id: str, limit: int):
        nonlocal active_reads, max_active_reads
        active_reads += 1
        max_active_reads = max(max_active_reads, active_reads)
        await asyncio.sleep(0.01)
        active_reads -= 1
        return [{"event_id": f"evt-{episode_id}"}]

    l2 = MagicMock()
    l2.get_experience_draft = AsyncMock(return_value=copy.deepcopy(draft))
    l2.list_episode_events = AsyncMock(side_effect=list_episode_events)
    l2.update_experience_draft = AsyncMock(return_value=True)

    with build_patcher(MagicMock(l2=l2)):
        response = TestClient(app).get(
            "/api/memory/l2/experience-drafts/draft-large",
        )

    assert response.status_code == 200
    assert response.json()["chapters"][0]["event_count"] == 30
    assert 1 < max_active_reads <= 8


def test_update_experience_draft_autosaves_editable_fields(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience_draft = AsyncMock(
        side_effect=[
            {"draft_id": "draft-japan", "status": "editing", "title": "日本旅行"},
            {"draft_id": "draft-japan", "status": "editing", "title": "十天日本旅行"},
        ]
    )
    l2.update_experience_draft = AsyncMock(return_value=True)
    unified = MagicMock()
    unified.l2 = l2

    with build_patcher(unified):
        response = TestClient(app).patch(
            "/api/memory/l2/experience-drafts/draft-japan",
            json={"title": "十天日本旅行"},
        )

    assert response.status_code == 200
    assert response.json()["title"] == "十天日本旅行"
    l2.update_experience_draft.assert_awaited_once_with(
        draft_id="draft-japan",
        title="十天日本旅行",
    )


def test_upload_experience_draft_cover_persists_local_asset(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience_draft = AsyncMock(
        side_effect=[
            {
                "draft_id": "draft-japan",
                "status": "editing",
                "title": "日本旅行",
                "chapters": [],
                "possible_evidence": [],
                "excluded_evidence": [],
            },
            {
                "draft_id": "draft-japan",
                "status": "editing",
                "title": "日本旅行",
                "user_cover_asset_ref": "manual-entry-asset://cover.jpg",
                "chapters": [],
                "possible_evidence": [],
                "excluded_evidence": [],
            },
        ]
    )
    l2.update_experience_draft = AsyncMock(return_value=True)
    unified = MagicMock(l2=l2)
    asset_store = MagicMock()

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes._resolve_manual_entry_asset_store",
            return_value=asset_store,
        ),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.store_uploaded_image_asset",
            new=AsyncMock(
                return_value={
                    "asset_ref": "manual-entry-asset://cover.jpg",
                    "content_type": "image/jpeg",
                }
            ),
        ) as store_asset,
    ):
        response = TestClient(app).post(
            "/api/memory/l2/experience-drafts/draft-japan/cover",
            files={"file": ("cover.jpg", b"image-bytes", "image/jpeg")},
        )

    assert response.status_code == 200
    assert response.json()["user_cover_asset_ref"] == "manual-entry-asset://cover.jpg"
    store_asset.assert_awaited_once()
    l2.update_experience_draft.assert_awaited_once_with(
        draft_id="draft-japan",
        user_cover_asset_ref="manual-entry-asset://cover.jpg",
    )


def test_create_experience_from_draft_returns_created_experience(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience_draft = AsyncMock(
        return_value={
            "draft_id": "draft-japan",
            "status": "editing",
            "title": "日本旅行",
        }
    )
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp-japan",
            "status": "active",
            "title": "日本旅行",
        }
    )
    unified = MagicMock()
    unified.l2 = l2

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.create_experience_from_draft",
            new=AsyncMock(return_value="exp-japan"),
        ) as create,
    ):
        response = TestClient(app).post(
            "/api/memory/l2/experience-drafts/draft-japan/create",
        )

    assert response.status_code == 200
    assert response.json()["experience_id"] == "exp-japan"
    create.assert_awaited_once_with(l2, draft_id="draft-japan")


def test_create_experience_from_completed_draft_returns_existing_experience(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience_draft = AsyncMock(
        return_value={
            "draft_id": "draft-japan",
            "status": "completed",
            "created_experience_id": "exp-japan",
        }
    )
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp-japan",
            "status": "active",
            "title": "日本旅行",
        }
    )

    with build_patcher(MagicMock(l2=l2)):
        response = TestClient(app).post(
            "/api/memory/l2/experience-drafts/draft-japan/create",
        )

    assert response.status_code == 200
    assert response.json()["experience_id"] == "exp-japan"
    assert response.json()["experience"]["experience_id"] == "exp-japan"
    assert l2.get_experience.await_count == 2
    l2.get_experience.assert_awaited_with(experience_id="exp-japan")


def test_create_experience_seed_from_episode_ids_can_promote(public_app_with_mock_memory):
    from magi.memory.l2.experiences.models import ExperiencePromotionStats

    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        side_effect=lambda *, episode_id: {"episode_id": episode_id, "status": "active"}
    )
    l2.add_experience_seed_evidence = AsyncMock(return_value=1)
    l2.get_experience_seed = AsyncMock(
        return_value={
            "seed_id": "seed1",
            "seed_type": "manual",
            "status": "promoted",
            "title": "Japan trip planning",
        }
    )
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Japan trip planning",
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_experience_members = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = None
    unified.scenario_llm_pool = object()

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.discover_manual_experience_seed",
            new=AsyncMock(return_value="seed1"),
        ) as discover_seed,
        patch(
            "magi.api.routers.memory.l2.experiences_routes.promote_experiences_from_episodes",
            new=AsyncMock(
                return_value=ExperiencePromotionStats(promoted=1, promoted_experience_ids=["exp1"])
            ),
        ) as promote,
    ):
        client = TestClient(app)
        response = client.post(
            "/api/memory/l2/experience-seeds",
            json={
                "episode_ids": ["ep1", "ep2"],
                "title_hint": "Japan trip planning",
                "promote_now": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["seed_id"] == "seed1"
    assert body["promoted_experience_id"] == "exp1"
    assert body["experience"]["experience_id"] == "exp1"
    discover_seed.assert_awaited_once_with(
        l2,
        episode_id="ep1",
        title="Japan trip planning",
    )
    l2.add_experience_seed_evidence.assert_awaited_once()
    assert l2.add_experience_seed_evidence.await_args.kwargs["evidence"][0]["ref_id"] == "ep2"
    promote.assert_awaited_once()
    assert promote.await_args.args == (l2,)
    assert promote.await_args.kwargs["target_seed_id"] == "seed1"
    assert "selector" not in promote.await_args.kwargs


def test_create_experience_seed_from_event_ids_resolves_episode(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.find_episode_for_event = AsyncMock(return_value={"episode_id": "ep-from-event"})
    l2.get_episode = AsyncMock(return_value={"episode_id": "ep-from-event", "status": "active"})
    l2.add_experience_seed_evidence = AsyncMock(return_value=0)
    l2.get_experience_seed = AsyncMock(
        return_value={
            "seed_id": "seed-event",
            "seed_type": "manual",
            "status": "accepted",
            "title": "Found from event",
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    unified.l1 = MagicMock()
    unified.l1.fetch_events = AsyncMock(
        return_value=[{"event_id": "evt1", "content": "Selected event"}]
    )

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.discover_manual_experience_seed",
            new=AsyncMock(return_value="seed-event"),
        ) as discover_seed,
    ):
        client = TestClient(app)
        response = client.post(
            "/api/memory/l2/experience-seeds",
            json={
                "event_ids": ["evt1"],
                "title_hint": "Found from event",
                "promote_now": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["seed_id"] == "seed-event"
    l2.find_episode_for_event.assert_awaited_once_with(event_id="evt1")
    discover_seed.assert_awaited_once_with(
        l2,
        episode_id="ep-from-event",
        title="Found from event",
    )


def test_create_experience_seed_rejects_invalidated_episode(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        return_value={
            "episode_id": "ep-private",
            "status": "invalidated",
            "summary": "Private generated summary",
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    unified.l1 = None

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.discover_manual_experience_seed",
            new=AsyncMock(),
        ) as discover_seed,
    ):
        response = TestClient(app).post(
            "/api/memory/l2/experience-seeds",
            json={"episode_ids": ["ep-private"]},
        )

    assert response.status_code == 409
    assert "Private generated summary" not in response.text
    discover_seed.assert_not_awaited()


def test_list_experience_seeds_returns_readable_candidates(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.list_experience_seeds = AsyncMock(
        return_value=[
            {
                "seed_id": "seed1",
                "seed_type": "project",
                "status": "candidate",
                "title": "",
                "description": "",
                "anchor_entity_ids": ["software:github"],
                "anchor_place_ids": [],
                "anchor_topic_keys": ["topic:pull-request"],
                "time_start": 1,
                "time_end": 2,
                "confidence": 0.7,
                "created_by": "system",
            }
        ]
    )
    l2.list_experience_seed_evidence = AsyncMock(
        return_value=[
            {"ref_type": "episode", "ref_id": "ep1", "role": "trigger"},
            {"ref_type": "episode", "ref_id": "ep2", "role": "support"},
        ]
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.get("/api/memory/l2/experience-seeds")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["seed_id"] == "seed1"
    assert item["display_title"] == "可能是围绕 github、pull request 的经历"
    assert item["display_tags"] == ["github", "pull request"]
    assert item["evidence_count"] == 2
    l2.list_experience_seeds.assert_awaited_once_with(
        status="candidate",
        limit=None,
    )


def test_promote_experience_seed_targets_selected_seed(public_app_with_mock_memory):
    from magi.memory.l2.experiences.models import ExperiencePromotionStats

    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience_seed = AsyncMock(
        side_effect=[
            {
                "seed_id": "seed1",
                "status": "candidate",
                "title": "Japan planning",
            },
            {
                "seed_id": "seed1",
                "status": "promoted",
                "title": "Japan planning",
                "promoted_experience_id": "exp1",
            },
        ]
    )
    l2.update_experience_seed = AsyncMock(return_value=True)
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Japan planning",
            "time_start": 1,
            "time_end": 2,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_experience_members = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = None
    unified.scenario_llm_pool = object()

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.promote_experiences_from_episodes",
            new=AsyncMock(
                return_value=ExperiencePromotionStats(promoted=1, promoted_experience_ids=["exp1"])
            ),
        ) as promote,
    ):
        client = TestClient(app)
        response = client.post("/api/memory/l2/experience-seeds/seed1/promote")

    assert response.status_code == 200
    assert response.json()["promoted_experience_id"] == "exp1"
    l2.update_experience_seed.assert_awaited_once_with(
        seed_id="seed1",
        expected_statuses=["candidate"],
        status="accepted",
    )
    promote.assert_awaited_once()
    assert promote.await_args.args == (l2,)
    assert promote.await_args.kwargs["target_seed_id"] == "seed1"
    assert "selector" not in promote.await_args.kwargs


@pytest.mark.parametrize("seed_status", ["stale", "rejected", "invalidated"])
def test_promote_experience_seed_rejects_inactive_seed(
    public_app_with_mock_memory,
    seed_status,
):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience_seed = AsyncMock(
        return_value={
            "seed_id": "seed1",
            "status": seed_status,
            "title": "Private stale seed",
            "promoted_experience_id": None,
        }
    )
    l2.update_experience_seed = AsyncMock(return_value=True)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.promote_experiences_from_episodes",
            new=AsyncMock(),
        ) as promote,
    ):
        response = TestClient(app).post("/api/memory/l2/experience-seeds/seed1/promote")

    assert response.status_code == 409
    l2.update_experience_seed.assert_not_awaited()
    promote.assert_not_awaited()


def test_promote_experience_seed_hides_invalidated_linked_experience(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience_seed = AsyncMock(
        return_value={
            "seed_id": "seed1",
            "status": "stale",
            "promoted_experience_id": "exp-private",
        }
    )
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp-private",
            "status": "invalidated",
            "title": "Private invalidated experience",
        }
    )
    l2.update_experience_seed = AsyncMock(return_value=True)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.promote_experiences_from_episodes",
            new=AsyncMock(),
        ) as promote,
    ):
        response = TestClient(app).post("/api/memory/l2/experience-seeds/seed1/promote")

    assert response.status_code == 404
    assert "Private invalidated experience" not in response.text
    l2.update_experience_seed.assert_not_awaited()
    promote.assert_not_awaited()


def test_promote_experience_seed_is_idempotent_for_active_link(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience_seed = AsyncMock(
        return_value={
            "seed_id": "seed1",
            "status": "promoted",
            "title": "Japan planning",
            "promoted_experience_id": "exp1",
        }
    )
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Japan planning",
            "time_start": 1,
            "time_end": 2,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_experience_members = AsyncMock(return_value=[])
    l2.update_experience_seed = AsyncMock(return_value=True)
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = None

    with (
        build_patcher(unified),
        patch(
            "magi.api.routers.memory.l2.experiences_routes.promote_experiences_from_episodes",
            new=AsyncMock(),
        ) as promote,
    ):
        response = TestClient(app).post("/api/memory/l2/experience-seeds/seed1/promote")

    assert response.status_code == 200
    assert response.json()["promoted_experience_id"] == "exp1"
    assert response.json()["experience"]["experience_id"] == "exp1"
    l2.update_experience_seed.assert_not_awaited()
    promote.assert_not_awaited()


def test_reject_experience_seed_marks_it_rejected(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.update_experience_seed = AsyncMock(return_value=True)
    l2.get_experience_seed = AsyncMock(
        return_value={
            "seed_id": "seed1",
            "status": "rejected",
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.post("/api/memory/l2/experience-seeds/seed1/reject")

    assert response.status_code == 200
    assert response.json()["seed"]["status"] == "rejected"
    l2.update_experience_seed.assert_awaited_once_with(seed_id="seed1", status="rejected")


def test_list_experiences_returns_active_reviews(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.list_experiences = AsyncMock(
        return_value=[
            {
                "experience_id": "exp1",
                "status": "active",
                "title": "Evaluate AI coding tools",
                "time_start": 1,
                "time_end": 2,
                "primary_entity_ids": [],
                "user_label": None,
                "user_note": None,
            }
        ]
    )
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(
        return_value={
            "summary_id": "sum1",
            "content": "Generated experience recap",
            "insight_metadata": {"label": "Generated experience title"},
            "updated_at": 10,
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3

    with build_patcher(unified):
        client = TestClient(app)
        response = client.get("/api/memory/l2/experiences")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["experience_review"]["label"] == "Generated experience title"
    assert item["display_title"] == "Generated experience title"
    assert item["display_description"] == "Generated experience recap"
    assert l2.list_experiences.await_args.kwargs["status"] == "active"


def test_list_experiences_extracts_structured_review_json(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.list_experiences = AsyncMock(
        return_value=[
            {
                "experience_id": "exp1",
                "status": "active",
                "title": "Fallback title",
                "time_start": 1,
                "time_end": 2,
                "primary_entity_ids": [],
                "user_label": None,
                "user_note": None,
            }
        ]
    )
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(
        return_value={
            "summary_id": "sum1",
            "content": json.dumps(
                {
                    "label": "调试 Tauri 与跑基准测试",
                    "content": "这段时间主要在调试本地热重载，并穿插跑基准测试。",
                    "key_topics": ["dev-tauri-hot.sh"],
                },
                ensure_ascii=False,
            ),
            "insight_metadata": {},
            "updated_at": 10,
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3

    with build_patcher(unified):
        client = TestClient(app)
        response = client.get("/api/memory/l2/experiences")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["experience_review"]["label"] == "调试 Tauri 与跑基准测试"
    assert (
        item["experience_review"]["content"] == "这段时间主要在调试本地热重载，并穿插跑基准测试。"
    )
    assert item["display_title"] == "调试 Tauri 与跑基准测试"
    assert item["display_description"] == "这段时间主要在调试本地热重载，并穿插跑基准测试。"
    assert "key_topics" not in item["display_description"]


def test_experience_detail_returns_source_episodes(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Evaluate tools",
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_experience_members = AsyncMock(
        return_value=[
            {
                "experience_id": "exp1",
                "member_type": "episode",
                "member_id": "ep1",
                "role": "core",
                "confidence": 0.8,
                "added_at": 5,
            }
        ]
    )
    l2.get_episode = AsyncMock(
        return_value={
            "episode_id": "ep1",
            "status": "active",
            "label": "Read tool docs",
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_episode_events = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.get("/api/memory/l2/experiences/exp1")

    assert response.status_code == 200
    body = response.json()
    assert body["experience_id"] == "exp1"
    assert body["source_episodes"][0]["episode_id"] == "ep1"
    assert body["source_episodes"][0]["membership_role"] == "core"


def test_experience_detail_omits_excluded_source_episodes(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Japan trip",
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_experience_members = AsyncMock(
        return_value=[
            {
                "experience_id": "exp1",
                "member_type": "episode",
                "member_id": "ep-core",
                "role": "core",
                "confidence": 0.8,
                "added_at": 5,
            },
            {
                "experience_id": "exp1",
                "member_type": "episode",
                "member_id": "ep-excluded",
                "role": "excluded",
                "confidence": 0.0,
                "added_at": 6,
            },
        ]
    )

    async def get_episode(*, episode_id: str):
        return {
            "episode_id": episode_id,
            "status": "active",
            "label": episode_id,
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }

    l2.get_episode = AsyncMock(side_effect=get_episode)
    l2.list_episode_events = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.get("/api/memory/l2/experiences/exp1")

    assert response.status_code == 200
    body = response.json()
    assert [item["episode_id"] for item in body["source_episodes"]] == ["ep-core"]


def test_experience_detail_omits_invalidated_source_episode_content(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Visible experience",
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_experience_members = AsyncMock(
        return_value=[
            {
                "experience_id": "exp1",
                "member_type": "episode",
                "member_id": "ep-private",
                "role": "core",
                "confidence": 0.8,
                "added_at": 5,
            }
        ]
    )
    l2.get_episode = AsyncMock(
        return_value={
            "episode_id": "ep-private",
            "status": "invalidated",
            "label": "Deleted private episode",
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_episode_events = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    l3.get_episodic_summary_by_episode_id = AsyncMock(
        return_value={
            "summary_id": "sum-private",
            "content": "Deleted private summary",
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = None

    with build_patcher(unified):
        response = TestClient(app).get("/api/memory/l2/experiences/exp1")

    assert response.status_code == 200
    assert response.json()["source_episodes"] == []
    assert "Deleted private episode" not in response.text
    assert "Deleted private summary" not in response.text
    l3.get_episodic_summary_by_episode_id.assert_not_awaited()


def test_experience_detail_uses_l3_labels_for_source_episodes(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Developer maintenance",
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_experience_members = AsyncMock(
        return_value=[
            {
                "experience_id": "exp1",
                "member_type": "episode",
                "member_id": "ep1",
                "role": "core",
                "confidence": 0.8,
                "added_at": 5,
            }
        ]
    )
    l2.get_episode = AsyncMock(
        return_value={
            "episode_id": "ep1",
            "status": "active",
            "label": "",
            "summary": "",
            "time_start": 1,
            "time_end": 4,
            "primary_entity_ids": [],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_episode_events = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    l3.get_episodic_summary_by_episode_id = AsyncMock(
        return_value={
            "summary_id": "sum1",
            "content": "Repeatedly restarted the local Tauri dev environment.",
            "insight_metadata": {"label": "调试 Tauri 热重载"},
            "updated_at": 10,
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.get("/api/memory/l2/experiences/exp1")

    assert response.status_code == 200
    body = response.json()
    assert body["source_episodes"][0]["display_title"] == "调试 Tauri 热重载"
    assert (
        body["source_episodes"][0]["display_description"]
        == "Repeatedly restarted the local Tauri dev environment."
    )


def test_annotate_experience_updates_user_fields(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.update_experience = AsyncMock(return_value=True)
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Generated",
            "time_start": 1,
            "time_end": 2,
            "primary_entity_ids": [],
            "user_label": "My title",
            "user_note": None,
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.patch(
            "/api/memory/l2/experiences/exp1",
            json={"user_label": "My title", "user_pinned": True},
        )

    assert response.status_code == 200
    l2.update_experience.assert_awaited_once_with(
        experience_id="exp1",
        expected_status="active",
        user_label="My title",
        user_pinned=True,
    )
    assert response.json()["display_title"] == "My title"


def test_hide_experience_sets_hidden_status(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.update_experience = AsyncMock(return_value=True)
    active = {
        "experience_id": "exp1",
        "status": "active",
        "title": "Generated",
        "time_start": 1,
        "time_end": 2,
        "primary_entity_ids": [],
    }
    hidden = {
        "experience_id": "exp1",
        "status": "hidden",
        "title": "Generated",
        "time_start": 1,
        "time_end": 2,
        "primary_entity_ids": [],
    }
    l2.get_experience = AsyncMock(side_effect=[active, hidden])
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.post("/api/memory/l2/experiences/exp1/hide")

    assert response.status_code == 200
    l2.update_experience.assert_awaited_once_with(
        experience_id="exp1",
        expected_status="active",
        status="hidden",
    )
    assert response.json()["status"] == "hidden"


def test_hide_invalidated_experience_does_not_restore_it(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp-private",
            "status": "invalidated",
            "title": "Deleted private experience",
        }
    )
    l2.update_experience = AsyncMock(return_value=True)
    unified = MagicMock(l2=l2, l3=None)

    with build_patcher(unified):
        response = TestClient(app).post("/api/memory/l2/experiences/exp-private/hide")

    assert response.status_code == 404
    assert "Deleted private experience" not in response.text
    l2.update_experience.assert_not_awaited()


def test_regenerate_experience_review_binds_source_experience_id(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience = AsyncMock(
        return_value={
            "experience_id": "exp1",
            "status": "active",
            "title": "Evaluate tools",
            "time_start": 1,
            "time_end": 2,
            "primary_entity_ids": [],
        }
    )
    l2.list_experience_members = AsyncMock(
        return_value=[
            {"member_type": "episode", "member_id": "ep1", "role": "core", "confidence": 0.8}
        ]
    )
    l2.get_episode = AsyncMock(return_value={"episode_id": "ep1", "label": "Read docs"})
    l2.list_episode_events = AsyncMock(return_value=[{"event_id": "e1"}])
    l2.update_experience = AsyncMock(return_value=True)
    l3 = MagicMock()
    l3.generate_experience_summary = AsyncMock(
        return_value={
            "summary_id": "sum1",
            "content": "Generated experience recap",
            "insight_metadata": {
                "source_experience_id": "exp1",
                "label": "Generated title",
            },
            "updated_at": 5,
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = MagicMock()

    with build_patcher(unified):
        client = TestClient(app)
        response = client.post("/api/memory/l2/experiences/exp1/regenerate")

    assert response.status_code == 200
    l3.generate_experience_summary.assert_awaited_once()
    l2.update_experience.assert_awaited_once_with(
        experience_id="exp1",
        expected_status="active",
        title="Generated title",
        magi_interpretation="Generated experience recap",
    )
    assert response.json()["experience_review"]["label"] == "Generated title"
    assert response.json()["experience_review"]["content"] == "Generated experience recap"


def test_regenerate_experience_does_not_return_content_deleted_during_generation(
    public_app_with_mock_memory,
):
    app, build_patcher = public_app_with_mock_memory
    active = {
        "experience_id": "exp-private-race",
        "status": "active",
        "title": "Private experience",
        "time_start": 1,
        "time_end": 2,
        "primary_entity_ids": [],
    }
    invalidated = {**active, "status": "invalidated"}
    l2 = MagicMock()
    l2.get_experience = AsyncMock(side_effect=[active, invalidated])
    l2.list_experience_members = AsyncMock(return_value=[])
    l2.update_experience = AsyncMock(return_value=True)
    l3 = MagicMock()
    l3.generate_experience_summary = AsyncMock(
        return_value={
            "summary_id": "sum-private-race",
            "content": "Deleted private recap",
            "insight_metadata": {"label": "Deleted private title"},
        }
    )
    unified = MagicMock(l1=MagicMock(), l2=l2, l3=l3)

    with build_patcher(unified):
        response = TestClient(app).post("/api/memory/l2/experiences/exp-private-race/regenerate")

    assert response.status_code == 404
    assert "Deleted private" not in response.text
    l2.update_experience.assert_not_awaited()
