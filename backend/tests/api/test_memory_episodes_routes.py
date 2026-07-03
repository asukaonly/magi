"""Integration tests for /memory/l2/episodes surface + reconsolidate."""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory.router import memory_router
from magi.memory.l2.consolidation_schedule import TARGET_KEY_L2_CONSOLIDATE
from magi.memory.l2.store import L2CognitionStore
from magi.scheduler.contracts import ScheduledTargetType
from magi.scheduler.repository import ScheduleRepository


@pytest.fixture
def app_with_mock_memory():
    """Mount memory_router, patch the dependency resolver to return a mock unified store."""
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    def _build(unified_memory):
        # Patch the resolver function used by the route handlers.
        return patch(
            "magi.api.routers.memory.l2.episodes_routes._resolve_unified_memory",
            return_value=unified_memory,
        )

    return app, _build


@contextmanager
def _patched_l2_consolidation_lock():
    repository = MagicMock()
    acquire = AsyncMock(return_value=repository)
    record_success = AsyncMock()
    record_failure = AsyncMock()
    with (
        patch(
            "magi.api.services.l2_episode_review_service._acquire_l2_consolidation_lock",
            new=acquire,
        ),
        patch(
            "magi.api.services.l2_episode_review_service._record_l2_consolidation_lock_success",
            new=record_success,
        ),
        patch(
            "magi.api.services.l2_episode_review_service._record_l2_consolidation_lock_failure",
            new=record_failure,
        ),
    ):
        yield acquire, record_success, record_failure


def test_list_episodes_surface_standout_returns_only_standouts(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_standout_episodes = AsyncMock(return_value=[
        {"episode_id": "ep1", "episode_type": "activity", "user_pinned": False, "magi_standout": True,
         "time_start": 100, "time_end": 200, "primary_entity_ids": [], "summary": None, "label": None,
         "user_label": None, "user_note": None, "status": "active"},
    ])
    l3 = MagicMock()
    l3.get_episodic_summary_by_episode_id = AsyncMock(return_value={
        "summary_id": "sum1",
        "content": "你和 Kimi 的一段下午",
        "insight_metadata": {"label": "Kimi 下午"},
        "updated_at": 1700000000,
    })
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes", params={"surface": "standout"})
    assert r.status_code == 200
    body = r.json()
    assert body["surface"] == "standout"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["episode_summary"]["content"] == "你和 Kimi 的一段下午"
    assert item["episode_summary"]["label"] == "Kimi 下午"


def test_list_episodes_surface_standout_null_summary_when_no_l3(app_with_mock_memory):
    """When l3 is None, all items get summary=null."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_standout_episodes = AsyncMock(return_value=[
        {"episode_id": "ep2", "episode_type": "visit", "user_pinned": True, "magi_standout": False,
         "time_start": 50, "time_end": 150, "primary_entity_ids": [], "status": "user_pinned"},
    ])
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes", params={"surface": "standout"})
    assert r.status_code == 200
    body = r.json()
    assert body["surface"] == "standout"
    assert body["items"][0]["episode_summary"] is None


def test_list_episodes_surface_standout_null_summary_when_not_generated(app_with_mock_memory):
    """When l3 has no episodic summary for the episode, summary=null."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_standout_episodes = AsyncMock(return_value=[
        {"episode_id": "ep3", "episode_type": "activity", "user_pinned": False, "magi_standout": True,
         "time_start": 0, "time_end": 100, "primary_entity_ids": [], "status": "active"},
    ])
    l3 = MagicMock()
    l3.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes", params={"surface": "standout"})
    assert r.status_code == 200
    assert r.json()["items"][0]["episode_summary"] is None


def test_list_episodes_default_surface_lists_active(app_with_mock_memory):
    """Without an explicit status, the experience page lists active episodes."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_episodes = AsyncMock(return_value=[{"episode_id": "ep1"}])
    l2.count_episodes = AsyncMock(return_value=1)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert "surface" not in body
    assert l2.list_episodes.await_args.kwargs["status"] == "active"
    assert l2.count_episodes.await_args.kwargs["status"] == "active"
    l2.list_standout_episodes.assert_not_called()


def test_list_episodes_default_surface_includes_episodic_summary(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_episodes = AsyncMock(
        return_value=[
            {
                "episode_id": "ep1",
                "user_label": None,
                "user_note": None,
            }
        ]
    )
    l2.count_episodes = AsyncMock(return_value=1)
    l3 = MagicMock()
    l3.get_episodic_summary_by_episode_id = AsyncMock(
        return_value={
            "summary_id": "sum1",
            "content": "Generated recap",
            "insight_metadata": {"label": "Generated title"},
            "updated_at": 4,
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3

    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes")

    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["episode_summary"]["label"] == "Generated title"
    assert item["display_title"] == "Generated title"
    assert item["display_description"] == "Generated recap"


def test_episode_detail_returns_events_and_inferred(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        return_value={"episode_id": "ep1", "status": "active", "time_start": 1, "time_end": 2}
    )
    l2.list_episode_events = AsyncMock(return_value=[{"event_id": "e1"}])
    l2.list_assertions_for_episode = AsyncMock(
        return_value=[
            {
                "assertion_id": "assert-1",
                "entity_id": "user",
                "entity_type": "user",
                "trait_family": "preference",
                "trait_name": "balance",
                "trait_value": "values work-life balance",
                "confidence_score": 0.7,
                "natural_summary": "User values balance.",
                "validation_state": "tentative",
                "user_feedback": None,
                "evidence_events": ["e1"],
            }
        ]
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    unified.l1 = None
    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes/ep1")

    assert r.status_code == 200
    body = r.json()
    assert body["events"][0]["event_id"] == "e1"
    assert body["inferred"][0]["assertion_id"] == "assert-1"
    assert body["inferred"][0]["trait_name"] == "balance"
    l2.list_assertions_for_episode.assert_awaited_once_with(episode_id="ep1")


def test_episode_detail_returns_display_fields_summary_and_hydrated_events(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        return_value={
            "episode_id": "ep1",
            "status": "active",
            "time_start": 1,
            "time_end": 2,
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_episode_events = AsyncMock(
        return_value=[
            {
                "episode_id": "ep1",
                "event_id": "e1",
                "membership_role": "member",
                "membership_confidence": 0.8,
                "added_at": 3,
            }
        ]
    )
    l2.list_assertions_for_episode = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.get_episodic_summary_by_episode_id = AsyncMock(
        return_value={
            "summary_id": "sum1",
            "content": "Generated recap",
            "insight_metadata": {"label": "Generated title"},
            "updated_at": 4,
        }
    )
    l1 = MagicMock()
    l1.get_events_by_ids = AsyncMock(
        return_value=[
            {
                "event_id": "e1",
                "timestamp": 1.5,
                "event_type": "UserMessage",
                "source": "chat",
                "content": "Talked about the trip.",
            }
        ]
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = l1

    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes/ep1")

    assert r.status_code == 200
    body = r.json()
    assert body["episode_summary"]["content"] == "Generated recap"
    assert body["display_title"] == "Generated title"
    assert body["display_description"] == "Generated recap"
    assert body["display_source"] == "generated"
    assert body["events"][0]["content_preview"] == "Talked about the trip."
    l1.get_events_by_ids.assert_awaited_once_with(["e1"])


def test_episode_detail_hydrates_real_l1_events_and_entity_names(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        return_value={
            "episode_id": "ep1",
            "status": "active",
            "time_start": 1,
            "time_end": 2,
            "primary_entity_ids": ["software:gmail", "media:8ab2042a42e5", "user:local_user"],
            "user_label": None,
            "user_note": None,
        }
    )
    l2.list_episode_events = AsyncMock(
        return_value=[
            {
                "episode_id": "ep1",
                "event_id": "e1",
                "membership_role": "member",
                "membership_confidence": 0.8,
                "added_at": 3,
            }
        ]
    )
    l2.list_assertions_for_episode = AsyncMock(return_value=[])

    class FetchOnlyL1:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        async def fetch_events(self, event_ids, **_kwargs):
            self.calls.append(list(event_ids))
            return [
                {
                    "event_id": "e1",
                    "timestamp": 1.5,
                    "event_type": "SENSOR_EVENT",
                    "source": "chrome_history",
                    "content": "Chrome 浏览 Gmail：iKuuu VPN 流量重置通知。",
                }
            ]

    class EntityCatalog:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        async def list_entities(self, *, limit, entity_ids=None, **_kwargs):
            self.calls.append(list(entity_ids or []))
            return [
                {
                    "entity_id": "software:gmail",
                    "canonical_name": "Gmail",
                    "entity_type": "software",
                },
                {
                    "entity_id": "media:8ab2042a42e5",
                    "canonical_name": "张雪峰快跑",
                    "entity_type": "media",
                },
            ][:limit]

    l1 = FetchOnlyL1()
    catalog = EntityCatalog()
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    unified.l1 = l1
    unified.l2_entity_catalog = catalog

    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes/ep1")

    assert r.status_code == 200
    body = r.json()
    assert body["events"][0]["content_preview"] == "Chrome 浏览 Gmail：iKuuu VPN 流量重置通知。"
    assert body["events"][0]["source"] == "chrome_history"
    assert body["primary_entities"] == [
        {"id": "software:gmail", "name": "Gmail", "type": "software"},
        {"id": "media:8ab2042a42e5", "name": "张雪峰快跑", "type": "media"},
    ]
    assert l1.calls == [["e1"]]
    assert catalog.calls == [["software:gmail", "media:8ab2042a42e5", "user:local_user"]]


def test_rejecting_episode_inference_removes_it(tmp_path):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    async def _seed() -> tuple[L2CognitionStore, str]:
        store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
        await store.initialize()
        now = time.time()
        await store.create_episode(
            episode_id="ep1",
            status="active",
            time_start=now - 10,
            time_end=now,
        )
        await store.add_episode_events(episode_id="ep1", event_ids=["e1"])
        assertion_id = await store.upsert_assertion_candidate(
            {
                "entity_id": "user",
                "entity_type": "user",
                "trait_family": "preference",
                "trait_name": "balance",
                "trait_value": "values work-life balance",
                "confidence_score": 0.7,
                "evidence_events": ["e1"],
                "volatility_index": 0.3,
                "source_domain": "chat",
                "inference_depth": "explicit",
                "validation_state": "tentative",
                "first_inferred_at": now,
                "last_validated_at": now,
                "natural_summary": "User values balance.",
            }
        )
        return store, assertion_id

    l2, assertion_id = asyncio.run(_seed())
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    with patch(
        "magi.api.routers.memory.l2.episodes_routes._resolve_unified_memory",
        return_value=unified,
    ), patch(
        "magi.api.routers.memory.l2.knowledge_routes._resolve_unified_memory",
        return_value=unified,
    ):
        client = TestClient(app)
        detail = client.get("/api/memory/l2/episodes/ep1").json()
        assert detail["inferred"][0]["assertion_id"] == assertion_id

        feedback = client.patch(
            f"/api/memory/l2/assertions/{assertion_id}/feedback",
            json={"feedback": "rejected"},
        )
        assert feedback.status_code == 200

        after = client.get("/api/memory/l2/episodes/ep1").json()
        assert all(item["assertion_id"] != assertion_id for item in after["inferred"])


def test_merge_episode_endpoint_calls_store(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.merge_episodes = AsyncMock(
        return_value={
            "episode_id": "target",
            "status": "active",
            "source_event_count": 3,
            "time_start": 1,
            "time_end": 4,
        }
    )
    l2.list_episode_events = AsyncMock(return_value=[])
    l2.list_assertions_for_episode = AsyncMock(return_value=[])
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    unified.l1 = None
    with build_patcher(unified):
        client = TestClient(app)
        r = client.post(
            "/api/memory/l2/episodes/target/merge",
            json={"absorbed_id": "source"},
        )

    assert r.status_code == 200
    assert r.json()["episode_id"] == "target"
    l2.merge_episodes.assert_awaited_once_with(
        survivor_id="target",
        absorbed_id="source",
    )


def test_merge_candidates_rank_nearby_similar_episodes(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    source = {
        "episode_id": "source",
        "status": "active",
        "time_start": 100.0,
        "time_end": 200.0,
        "primary_topic_keys": ["japan"],
        "primary_place_ids": ["place:tokyo"],
    }
    candidate = {
        "episode_id": "candidate",
        "status": "active",
        "time_start": 210.0,
        "time_end": 260.0,
        "primary_topic_keys": ["japan"],
        "primary_place_ids": ["place:tokyo"],
    }
    l2 = MagicMock()
    l2.get_episode = AsyncMock(return_value=source)
    l2.list_episodes = AsyncMock(return_value=[source, candidate])
    l3 = MagicMock()
    l3.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3

    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes/source/merge-candidates")

    assert r.status_code == 200
    body = r.json()
    assert [item["episode_id"] for item in body["items"]] == ["candidate"]
    assert body["items"][0]["candidate_score"] > 0
    assert "nearby_time" in body["items"][0]["candidate_reasons"]


def test_merge_episode_regenerates_survivor_summary(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    survivor = {"episode_id": "target", "status": "active", "user_label": None}
    l2.merge_episodes = AsyncMock(return_value=survivor)
    l2.list_episode_events = AsyncMock(
        return_value=[{"episode_id": "target", "event_id": "e1"}]
    )
    l2.index_episode_fts = AsyncMock()
    l2.update_episode = AsyncMock(return_value=True)
    l2.list_assertions_for_episode = AsyncMock(return_value=[])
    l1 = MagicMock()
    l1.get_events_by_ids = AsyncMock(
        return_value=[{"event_id": "e1", "timestamp": 10.0, "content": "Merged event"}]
    )
    l3 = MagicMock()
    l3.generate_episodic_summary = AsyncMock(
        return_value={
            "summary_id": "sum-merged",
            "content": "Merged recap",
            "insight_metadata": {"label": "Merged title"},
            "updated_at": 11,
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l1 = l1
    unified.l3 = l3

    with build_patcher(unified):
        client = TestClient(app)
        r = client.post(
            "/api/memory/l2/episodes/target/merge",
            json={"absorbed_id": "source"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["episode_summary"]["content"] == "Merged recap"
    assert body["display_title"] == "Merged title"


def test_split_preview_returns_two_chronological_sides(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        return_value={"episode_id": "ep1", "time_start": 100.0, "time_end": 300.0}
    )
    l2.list_episode_events = AsyncMock(
        return_value=[
            {"episode_id": "ep1", "event_id": "e2", "added_at": 2},
            {"episode_id": "ep1", "event_id": "e1", "added_at": 1},
            {"episode_id": "ep1", "event_id": "e3", "added_at": 3},
        ]
    )
    l2.split_episode = AsyncMock()
    l1 = MagicMock()
    l1.get_events_by_ids = AsyncMock(
        return_value=[
            {"event_id": "e1", "timestamp": 100.0, "content": "First"},
            {"event_id": "e2", "timestamp": 200.0, "content": "Second"},
            {"event_id": "e3", "timestamp": 300.0, "content": "Third"},
        ]
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l1 = l1
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        r = client.post(
            "/api/memory/l2/episodes/ep1/split-preview",
            json={"break_after_event_id": "e2"},
        )

    assert r.status_code == 200
    body = r.json()
    assert [item["event_id"] for item in body["left"]["events"]] == ["e1", "e2"]
    assert [item["event_id"] for item in body["right"]["events"]] == ["e3"]
    assert body["left"]["event_count"] == 2
    assert body["right"]["event_count"] == 1
    l2.split_episode.assert_not_awaited()


def test_split_preview_rejects_last_event_breakpoint(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        return_value={"episode_id": "ep1", "time_start": 100.0, "time_end": 300.0}
    )
    l2.list_episode_events = AsyncMock(
        return_value=[
            {"episode_id": "ep1", "event_id": "e1", "added_at": 1},
            {"episode_id": "ep1", "event_id": "e2", "added_at": 2},
        ]
    )
    l2.split_episode = AsyncMock()
    l1 = MagicMock()
    l1.get_events_by_ids = AsyncMock(
        return_value=[
            {"event_id": "e1", "timestamp": 100.0, "content": "First"},
            {"event_id": "e2", "timestamp": 200.0, "content": "Second"},
        ]
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l1 = l1
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        r = client.post(
            "/api/memory/l2/episodes/ep1/split-preview",
            json={"break_after_event_id": "e2"},
        )

    assert r.status_code == 409
    l2.split_episode.assert_not_awaited()


def test_split_episode_calls_store_and_regenerates_children(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    source = {"episode_id": "ep1", "time_start": 100.0, "time_end": 400.0}
    left = {"episode_id": "ep1-left", "status": "active", "user_label": None}
    right = {"episode_id": "ep1-right", "status": "active", "user_label": None}
    source_memberships = [
        {"episode_id": "ep1", "event_id": "e1", "added_at": 1},
        {"episode_id": "ep1", "event_id": "e2", "added_at": 2},
        {"episode_id": "ep1", "event_id": "e3", "added_at": 3},
        {"episode_id": "ep1", "event_id": "e4", "added_at": 4},
    ]
    event_rows = {
        "e1": {"event_id": "e1", "timestamp": 100.0, "content": "One"},
        "e2": {"event_id": "e2", "timestamp": 200.0, "content": "Two"},
        "e3": {"event_id": "e3", "timestamp": 300.0, "content": "Three"},
        "e4": {"event_id": "e4", "timestamp": 400.0, "content": "Four"},
    }

    async def _get_events_by_ids(event_ids):
        return [event_rows[event_id] for event_id in event_ids if event_id in event_rows]

    async def _generate_summary(*, l1_store, episode, episode_event_ids):
        episode_id = episode["episode_id"]
        return {
            "summary_id": f"sum-{episode_id}",
            "content": f"Recap {episode_id}",
            "insight_metadata": {"label": f"Title {episode_id}"},
            "updated_at": 10,
        }

    l2 = MagicMock()
    l2.get_episode = AsyncMock(return_value=source)
    l2.list_episode_events = AsyncMock(
        side_effect=[
            source_memberships,
            source_memberships[:2],
            source_memberships[2:],
        ]
    )
    l2.split_episode = AsyncMock(return_value={"left": left, "right": right})
    l2.index_episode_fts = AsyncMock()
    l2.update_episode = AsyncMock(return_value=True)
    l2.list_assertions_for_episode = AsyncMock(return_value=[])
    l1 = MagicMock()
    l1.get_events_by_ids = AsyncMock(side_effect=_get_events_by_ids)
    l3 = MagicMock()
    l3.generate_episodic_summary = AsyncMock(side_effect=_generate_summary)
    unified = MagicMock()
    unified.l2 = l2
    unified.l1 = l1
    unified.l3 = l3

    with build_patcher(unified):
        client = TestClient(app)
        r = client.post(
            "/api/memory/l2/episodes/ep1/split",
            json={"break_after_event_id": "e2"},
        )

    assert r.status_code == 200
    body = r.json()
    assert [item["episode_id"] for item in body["items"]] == ["ep1-left", "ep1-right"]
    assert body["items"][0]["episode_summary"]["content"] == "Recap ep1-left"
    assert body["items"][1]["episode_summary"]["content"] == "Recap ep1-right"
    split_kwargs = l2.split_episode.await_args.kwargs
    assert split_kwargs["source_episode_id"] == "ep1"
    assert split_kwargs["left_event_ids"] == ["e1", "e2"]
    assert split_kwargs["right_event_ids"] == ["e3", "e4"]
    assert split_kwargs["left_time_start"] == 100.0
    assert split_kwargs["left_time_end"] == 200.0
    assert split_kwargs["right_time_start"] == 300.0
    assert split_kwargs["right_time_end"] == 400.0
    assert l3.generate_episodic_summary.await_count == 2


def test_regenerate_episode_calls_l3_and_indexes_fts(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(return_value={"episode_id": "ep1", "user_label": "Trip"})
    l2.list_episode_events = AsyncMock(return_value=[{"event_id": "e1"}])
    l2.index_episode_fts = AsyncMock()
    l2.update_episode = AsyncMock(return_value=True)
    l2.list_assertions_for_episode = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.generate_episodic_summary = AsyncMock(
        return_value={
            "summary_id": "sum2",
            "content": "New recap",
            "insight_metadata": {"label": "New title"},
            "updated_at": 10,
        }
    )
    l1 = MagicMock()
    l1.get_events_by_ids = AsyncMock(return_value=[])
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = l1

    with build_patcher(unified):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/ep1/regenerate")

    assert r.status_code == 200
    body = r.json()
    assert body["episode_summary"]["content"] == "New recap"
    assert body["display_title"] == "Trip"
    l3.generate_episodic_summary.assert_awaited_once_with(
        l1_store=l1,
        episode={"episode_id": "ep1", "user_label": "Trip"},
        episode_event_ids=["e1"],
    )
    l2.index_episode_fts.assert_awaited_once_with(
        episode_id="ep1",
        summary="New recap",
        label="New title",
        user_label="Trip",
    )
    l2.update_episode.assert_awaited_once_with(
        episode_id="ep1",
        label="New title",
        summary="New recap",
    )


def test_regenerate_episode_route_is_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if getattr(route, "path", None):
            route_methods.setdefault(route.path, set()).update(route.methods or set())

    assert "POST" in route_methods["/l2/episodes/{episode_id}/regenerate"]


def test_event_candidates_exclude_existing_members(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        return_value={"episode_id": "ep1", "time_start": 100.0, "time_end": 200.0}
    )
    l2.list_episode_events = AsyncMock(return_value=[{"episode_id": "ep1", "event_id": "e1"}])
    l1 = MagicMock()
    l1.query_events = AsyncMock(
        return_value=[
            {"event_id": "e1", "timestamp": 120.0, "content": "Already in episode"},
            {"event_id": "e2", "timestamp": 180.0, "event_type": "UserMessage", "source": "chat", "content": "Candidate event"},
        ]
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l1 = l1
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes/ep1/event-candidates")

    assert r.status_code == 200
    body = r.json()
    assert [item["event_id"] for item in body["items"]] == ["e2"]
    assert body["items"][0]["content_preview"] == "Candidate event"
    l1.query_events.assert_awaited_once()


def test_add_episode_events_route_updates_memberships_and_regenerates(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    episode = {"episode_id": "ep1", "time_start": 100.0, "time_end": 200.0, "user_label": None}
    l2.get_episode = AsyncMock(return_value=episode)
    l2.list_episode_events = AsyncMock(
        side_effect=[
            [{"episode_id": "ep1", "event_id": "e1"}],
            [{"episode_id": "ep1", "event_id": "e1"}, {"episode_id": "ep1", "event_id": "e2"}],
        ]
    )
    l2.add_episode_events = AsyncMock(return_value=1)
    l2.update_episode = AsyncMock(return_value=True)
    l2.index_episode_fts = AsyncMock()
    l2.list_assertions_for_episode = AsyncMock(return_value=[])
    l1 = MagicMock()
    l1.query_events = AsyncMock(
        return_value=[
            {"event_id": "e2", "timestamp": 180.0, "content": "Candidate event"},
        ]
    )
    l1.get_events_by_ids = AsyncMock(
        return_value=[
            {"event_id": "e1", "timestamp": 120.0, "content": "Existing"},
            {"event_id": "e2", "timestamp": 180.0, "content": "Candidate event"},
        ]
    )
    l3 = MagicMock()
    l3.generate_episodic_summary = AsyncMock(
        return_value={
            "summary_id": "sum1",
            "content": "Updated recap",
            "insight_metadata": {"label": "Updated title"},
            "updated_at": 9,
        }
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l1 = l1
    unified.l3 = l3

    with build_patcher(unified):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/ep1/events", json={"event_ids": ["e2"]})

    assert r.status_code == 200
    assert r.json()["episode_summary"]["content"] == "Updated recap"
    l2.add_episode_events.assert_awaited_once_with(episode_id="ep1", event_ids=["e2"])
    l2.update_episode.assert_any_await(
        episode_id="ep1",
        source_event_count=2,
        time_start=120.0,
        time_end=180.0,
    )
    # Regeneration also back-writes the refreshed label/summary.
    l2.update_episode.assert_any_await(
        episode_id="ep1",
        label="Updated title",
        summary="Updated recap",
    )


def test_remove_episode_events_rejects_too_few_remaining_events(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.get_episode = AsyncMock(
        return_value={"episode_id": "ep1", "time_start": 100.0, "time_end": 200.0}
    )
    l2.list_episode_events = AsyncMock(
        return_value=[
            {"episode_id": "ep1", "event_id": "e1"},
            {"episode_id": "ep1", "event_id": "e2"},
        ]
    )
    l2.remove_episode_events = AsyncMock()
    unified = MagicMock()
    unified.l2 = l2
    unified.l1 = None
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        r = client.request(
            "DELETE",
            "/api/memory/l2/episodes/ep1/events",
            json={"event_ids": ["e1"]},
        )

    assert r.status_code == 409
    l2.remove_episode_events.assert_not_awaited()


def test_episode_event_edit_routes_are_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if getattr(route, "path", None):
            route_methods.setdefault(route.path, set()).update(route.methods or set())

    assert "GET" in route_methods["/l2/episodes/{episode_id}/event-candidates"]
    assert "POST" in route_methods["/l2/episodes/{episode_id}/events"]
    assert "DELETE" in route_methods["/l2/episodes/{episode_id}/events"]


def test_merge_episode_route_is_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if getattr(route, "path", None):
            route_methods.setdefault(route.path, set()).update(route.methods or set())

    assert "GET" in route_methods["/l2/episodes/{episode_id}/merge-candidates"]
    assert "/l2/episodes/{episode_id}/merge" in route_methods
    assert "POST" in route_methods["/l2/episodes/{episode_id}/merge"]


def test_episode_split_routes_are_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if getattr(route, "path", None):
            route_methods.setdefault(route.path, set()).update(route.methods or set())

    assert "POST" in route_methods["/l2/episodes/{episode_id}/split-preview"]
    assert "POST" in route_methods["/l2/episodes/{episode_id}/split"]


def test_episode_read_and_annotation_routes_are_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if getattr(route, "path", None):
            route_methods.setdefault(route.path, set()).update(route.methods or set())

    assert "GET" in route_methods["/l2/episodes"]
    assert "GET" in route_methods["/l2/episodes/{episode_id}"]
    assert "PATCH" in route_methods["/l2/episodes/{episode_id}"]


def test_experience_cover_route_is_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if getattr(route, "path", None):
            route_methods.setdefault(route.path, set()).update(route.methods or set())

    assert "POST" in route_methods["/l2/experiences/{experience_id}/cover"]


def test_upload_experience_cover_stores_asset_and_updates_experience(tmp_path):
    from magi.memory.manual_entries.asset_store import ManualEntryAssetStore

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")
    asset_store = ManualEntryAssetStore(media_root=tmp_path)
    stored_ref: str | None = None
    l2 = MagicMock()

    async def _update_experience(**kwargs):
        nonlocal stored_ref
        stored_ref = kwargs["user_cover_asset_ref"]
        return True

    async def _get_experience(*, experience_id: str):
        return {
            "experience_id": experience_id,
            "status": "active",
            "title": "Japan trip",
            "time_start": 1.0,
            "time_end": 2.0,
            "user_cover_asset_ref": stored_ref,
            "primary_entity_ids": [],
            "primary_place_ids": [],
            "primary_topic_keys": [],
        }

    l2.update_experience = AsyncMock(side_effect=_update_experience)
    l2.get_experience = AsyncMock(side_effect=_get_experience)
    l2.list_experience_members = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3

    with (
        patch(
            "magi.api.routers.memory.l2.experiences_routes._resolve_unified_memory",
            return_value=unified,
        ),
        patch(
            "magi.api.routers.memory.l2.experiences_routes._resolve_manual_entry_asset_store",
            return_value=asset_store,
            create=True,
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/memory/l2/experiences/exp-cover/cover",
            files={"file": ("cover.png", b"\x89PNG\r\n\x1a\ncover", "image/png")},
        )

    assert response.status_code == 200
    body = response.json()
    asset_ref = body["user_cover_asset_ref"]
    assert asset_ref.startswith("manual-entry-asset://")
    assert asset_store.resolve(asset_ref) == (b"\x89PNG\r\n\x1a\ncover", "image/png")
    l2.update_experience.assert_awaited_once_with(
        experience_id="exp-cover",
        user_cover_asset_ref=asset_ref,
    )


def test_annotate_episode_pin_does_not_change_status(app_with_mock_memory):
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.update_episode = AsyncMock(return_value=True)
    l2.get_episode = AsyncMock(
        return_value={"episode_id": "ep1", "status": "active", "user_pinned": True}
    )
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.patch("/api/memory/l2/episodes/ep1", json={"user_pinned": True})

    assert response.status_code == 200
    assert l2.update_episode.await_args.kwargs == {
        "episode_id": "ep1",
        "user_pinned": 1,
    }


def test_list_episodes_insight_metadata_string_decoded(app_with_mock_memory):
    """insight_metadata stored as a JSON string is decoded correctly."""
    app, build_patcher = app_with_mock_memory
    import json as _json
    l2 = MagicMock()
    l2.list_standout_episodes = AsyncMock(return_value=[
        {"episode_id": "ep4", "episode_type": "activity", "magi_standout": True,
         "time_start": 0, "time_end": 100, "primary_entity_ids": [], "status": "active"},
    ])
    l3 = MagicMock()
    l3.get_episodic_summary_by_episode_id = AsyncMock(return_value={
        "summary_id": "sum4",
        "content": "content here",
        "insight_metadata": _json.dumps({"label": "from string"}),
        "updated_at": 999,
    })
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes", params={"surface": "standout"})
    assert r.status_code == 200
    assert r.json()["items"][0]["episode_summary"]["label"] == "from string"


def test_reconsolidate_generates_summaries_for_active_lacking_summary(app_with_mock_memory):
    """Reconsolidate: consolidate, then generate L3 summary for every active episode
    lacking one (widened from standout-only via l3.generate_missing_episodic_summaries)."""
    from magi.memory.l2.experiences.models import ExperiencePromotionStats

    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    # Catch-up scope is now ALL active episodes (not just standouts).
    l2.list_episodes = AsyncMock(return_value=[
        {"episode_id": "ep_has"},
        {"episode_id": "ep_need"},
    ])
    l2.list_experiences = AsyncMock(return_value=[
        {
            "experience_id": "exp_need",
            "title": "Launch week",
            "time_start": 1,
            "time_end": 2,
        }
    ])
    l2.get_experience = AsyncMock(return_value={
        "experience_id": "exp_need",
        "title": "Launch week",
        "time_start": 1,
        "time_end": 2,
    })
    l2.list_experience_members = AsyncMock(return_value=[
        {"member_type": "episode", "member_id": "ep_need", "role": "core", "confidence": 0.8}
    ])
    l3 = MagicMock()
    l3.generate_missing_episodic_summaries = AsyncMock(
        return_value={"generated": 1, "errors": []}
    )
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    l3.generate_experience_summary = AsyncMock(return_value={
        "summary_id": "sum-exp",
        "content": "Experience recap",
        "insight_metadata": {"source_experience_id": "exp_need"},
    })
    l1 = MagicMock()
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = l1

    # consolidate_episodes is invoked from within the route; patch where it's imported.
    with (
        build_patcher(unified),
        _patched_l2_consolidation_lock(),
        patch(
            "magi.memory.l2.episode_formation.consolidate_episodes",
            new=AsyncMock(return_value=MagicMock(
                promoted=2, standouts=1, merged=0, invalidated=0,
                promoted_episode_ids=["ep_need"],
            )),
        ),
        patch(
            "magi.memory.l2.experiences.promotion.promote_experiences_from_episodes",
            new=AsyncMock(return_value=ExperiencePromotionStats(
                candidates=1,
                promoted=1,
                promoted_experience_ids=["exp_need"],
            )),
        ),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 200
    body = r.json()
    assert body["promoted"] == 2
    assert body["standouts"] == 1
    assert body["summaries_generated"] == 1
    assert body["summary_errors"] == []
    assert body["experience_candidates"] == 1
    assert body["experiences_promoted"] == 1
    assert body["experience_summaries_generated"] == 1
    assert body["experience_summary_errors"] == []
    # Active episodes (not list_standout_episodes) drive the catch-up.
    l2.list_episodes.assert_awaited_once()
    assert l2.list_episodes.await_args.kwargs["status"] == "active"
    l3.generate_missing_episodic_summaries.assert_awaited_once()
    gen_kwargs = l3.generate_missing_episodic_summaries.await_args.kwargs
    assert gen_kwargs["episode_ids"] == ["ep_has", "ep_need"]
    assert gen_kwargs["l2_store"] is l2
    assert gen_kwargs["l1_store"] is l1
    l3.generate_experience_summary.assert_awaited_once()
    exp_kwargs = l3.generate_experience_summary.await_args.kwargs
    assert exp_kwargs["l1_store"] is l1
    assert exp_kwargs["l2_store"] is l2
    assert exp_kwargs["experience"]["experience_id"] == "exp_need"


def test_reconsolidate_refreshes_placeholder_experience_reviews(app_with_mock_memory):
    from magi.memory.l2.experiences.models import ExperiencePromotionStats

    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_episodes = AsyncMock(return_value=[])
    l2.list_experiences = AsyncMock(return_value=[
        {
            "experience_id": "exp-bad",
            "title": "Untitled experience / Untitled exper",
            "time_start": 1,
            "time_end": 2,
        }
    ])
    l2.get_experience = AsyncMock(return_value={
        "experience_id": "exp-bad",
        "title": "Untitled experience / Untitled exper",
        "time_start": 1,
        "time_end": 2,
    })
    l2.list_experience_members = AsyncMock(return_value=[
        {"member_type": "episode", "member_id": "ep-old", "role": "core", "confidence": 0.8}
    ])
    l3 = MagicMock()
    l3.generate_missing_episodic_summaries = AsyncMock(
        return_value={"generated": 0, "errors": []}
    )
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value={
        "summary_id": "sum-bad",
        "content": "Magi grouped related episode evidence into a narratable memory.",
        "insight_metadata": {"label": "Untitled experience / Untitled exper"},
    })
    l3.generate_experience_summary = AsyncMock(return_value={
        "summary_id": "sum-fixed",
        "content": "Reviewed real activity",
        "insight_metadata": {"source_experience_id": "exp-bad", "label": "Real activity"},
    })
    l1 = MagicMock()
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = l1

    with (
        build_patcher(unified),
        _patched_l2_consolidation_lock(),
        patch(
            "magi.memory.l2.episode_formation.consolidate_episodes",
            new=AsyncMock(return_value=MagicMock(
                promoted=0, standouts=0, merged=0, invalidated=0,
                promoted_episode_ids=[],
            )),
        ),
        patch(
            "magi.memory.l2.experiences.promotion.promote_experiences_from_episodes",
            new=AsyncMock(return_value=ExperiencePromotionStats()),
        ),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")

    assert r.status_code == 200
    body = r.json()
    assert body["experiences_promoted"] == 0
    assert body["experience_summaries_generated"] == 1
    l3.generate_experience_summary.assert_awaited_once()
    assert l3.generate_experience_summary.await_args.kwargs["experience"]["experience_id"] == "exp-bad"


def test_reconsolidate_captures_summary_errors(app_with_mock_memory):
    """Summary generation errors surface in summary_errors (from the L3 helper), not raised."""
    from magi.memory.l2.experiences.models import ExperiencePromotionStats

    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_episodes = AsyncMock(return_value=[{"episode_id": "ep_fail"}])
    l2.list_experiences = AsyncMock(return_value=[])
    l3 = MagicMock()
    l3.generate_missing_episodic_summaries = AsyncMock(
        return_value={"generated": 0, "errors": ["ep_fail: LLM timeout"]}
    )
    l1 = MagicMock()
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = l1

    with (
        build_patcher(unified),
        _patched_l2_consolidation_lock(),
        patch(
            "magi.memory.l2.episode_formation.consolidate_episodes",
            new=AsyncMock(return_value=MagicMock(
                promoted=0, standouts=1, merged=0, invalidated=0, promoted_episode_ids=[],
            )),
        ),
        patch(
            "magi.memory.l2.experiences.promotion.promote_experiences_from_episodes",
            new=AsyncMock(return_value=ExperiencePromotionStats()),
        ),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 200
    body = r.json()
    assert body["summaries_generated"] == 0
    assert len(body["summary_errors"]) == 1
    assert "ep_fail" in body["summary_errors"][0]
    assert body["experiences_promoted"] == 0
    assert body["experience_summaries_generated"] == 0


def test_reconsolidate_no_generation_when_l3_missing(app_with_mock_memory):
    """When L3 is unavailable, consolidation still runs and no summaries are generated."""
    from magi.memory.l2.experiences.models import ExperiencePromotionStats

    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_episodes = AsyncMock(return_value=[{"episode_id": "ep1"}])
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    unified.l1 = None

    with (
        build_patcher(unified),
        _patched_l2_consolidation_lock(),
        patch(
            "magi.memory.l2.episode_formation.consolidate_episodes",
            new=AsyncMock(return_value=MagicMock(
                promoted=1, standouts=0, merged=0, invalidated=0, promoted_episode_ids=["ep1"],
            )),
        ),
        patch(
            "magi.memory.l2.experiences.promotion.promote_experiences_from_episodes",
            new=AsyncMock(return_value=ExperiencePromotionStats(
                candidates=1,
                promoted=1,
                promoted_experience_ids=["exp1"],
            )),
        ),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 200
    body = r.json()
    assert body["promoted"] == 1
    assert body["summaries_generated"] == 0
    assert body["summary_errors"] == []
    assert body["experiences_promoted"] == 1
    assert body["experience_summaries_generated"] == 0


def test_reconsolidate_returns_409_when_l2_consolidation_running(
    app_with_mock_memory,
    runtime_paths_with_schema,
):
    """Manual reconsolidate shares the L2 consolidation target lock."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_episodes = AsyncMock(return_value=[])
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
    unified.l1 = None

    async def _acquire_running_lock() -> None:
        repository = ScheduleRepository(runtime_paths_with_schema.scheduler_db_path)
        await repository.initialize()
        acquired = await repository.acquire_target_lock(
            ScheduledTargetType.MEMORY_L2_CONSOLIDATE,
            TARGET_KEY_L2_CONSOLIDATE,
        )
        assert acquired is True

    asyncio.run(_acquire_running_lock())

    consolidate = AsyncMock(return_value=MagicMock(
        promoted=1,
        standouts=0,
        merged=0,
        invalidated=0,
        promoted_episode_ids=["ep1"],
    ))
    with (
        build_patcher(unified),
        patch(
            "magi.api.services.l2_episode_review_service.get_runtime_paths",
            return_value=runtime_paths_with_schema,
            create=True,
        ),
        patch(
            "magi.memory.l2.episode_formation.consolidate_episodes",
            new=consolidate,
        ),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")

    assert r.status_code == 409
    assert r.json()["detail"]
    consolidate.assert_not_awaited()


def test_reconsolidate_503_when_l2_missing(app_with_mock_memory):
    """Returns 503 when L2 store is not initialized."""
    app, build_patcher = app_with_mock_memory
    unified = MagicMock()
    unified.l2 = None
    with build_patcher(unified):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 503
