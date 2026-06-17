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
from magi.memory.l2.entities.maintenance import TARGET_KEY_L2_MAINTENANCE
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
def _patched_l2_maintenance_lock():
    repository = MagicMock()
    acquire = AsyncMock(return_value=repository)
    record_success = AsyncMock()
    record_failure = AsyncMock()
    with (
        patch(
            "magi.api.routers.memory.l2.episodes_routes._acquire_l2_maintenance_lock",
            new=acquire,
        ),
        patch(
            "magi.api.routers.memory.l2.episodes_routes._record_l2_maintenance_lock_success",
            new=record_success,
        ),
        patch(
            "magi.api.routers.memory.l2.episodes_routes._record_l2_maintenance_lock_failure",
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
    unified = MagicMock(); unified.l2 = l2; unified.l3 = l3
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
    unified = MagicMock(); unified.l2 = l2; unified.l3 = None
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
    unified = MagicMock(); unified.l2 = l2; unified.l3 = l3
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
    unified = MagicMock(); unified.l2 = l2; unified.l3 = None
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
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None
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


def test_merge_episode_route_is_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if getattr(route, "path", None):
            route_methods.setdefault(route.path, set()).update(route.methods or set())

    assert "/l2/episodes/{episode_id}/merge" in route_methods
    assert "POST" in route_methods["/l2/episodes/{episode_id}/merge"]


def test_episode_read_and_annotation_routes_are_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if getattr(route, "path", None):
            route_methods.setdefault(route.path, set()).update(route.methods or set())

    assert "GET" in route_methods["/l2/episodes"]
    assert "GET" in route_methods["/l2/episodes/{episode_id}"]
    assert "PATCH" in route_methods["/l2/episodes/{episode_id}"]


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
    unified = MagicMock(); unified.l2 = l2; unified.l3 = l3
    with build_patcher(unified):
        client = TestClient(app)
        r = client.get("/api/memory/l2/episodes", params={"surface": "standout"})
    assert r.status_code == 200
    assert r.json()["items"][0]["episode_summary"]["label"] == "from string"


def test_reconsolidate_generates_summaries_for_active_lacking_summary(app_with_mock_memory):
    """Reconsolidate: consolidate, then generate L3 summary for every active episode
    lacking one (widened from standout-only via l3.generate_missing_episodic_summaries)."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    # Catch-up scope is now ALL active episodes (not just standouts).
    l2.list_episodes = AsyncMock(return_value=[
        {"episode_id": "ep_has"},
        {"episode_id": "ep_need"},
    ])
    l3 = MagicMock()
    l3.generate_missing_episodic_summaries = AsyncMock(
        return_value={"generated": 1, "errors": []}
    )
    l1 = MagicMock()
    unified = MagicMock(); unified.l2 = l2; unified.l3 = l3; unified.l1 = l1

    # consolidate_episodes is invoked from within the route; patch where it's imported.
    with (
        build_patcher(unified),
        _patched_l2_maintenance_lock(),
        patch(
            "magi.memory.l2.episode_formation.consolidate_episodes",
            new=AsyncMock(return_value=MagicMock(
                promoted=2, standouts=1, merged=0, invalidated=0,
                promoted_episode_ids=["ep_need"],
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
    # Active episodes (not list_standout_episodes) drive the catch-up.
    l2.list_episodes.assert_awaited_once()
    assert l2.list_episodes.await_args.kwargs["status"] == "active"
    l3.generate_missing_episodic_summaries.assert_awaited_once()
    gen_kwargs = l3.generate_missing_episodic_summaries.await_args.kwargs
    assert gen_kwargs["episode_ids"] == ["ep_has", "ep_need"]
    assert gen_kwargs["l2_store"] is l2
    assert gen_kwargs["l1_store"] is l1


def test_reconsolidate_captures_summary_errors(app_with_mock_memory):
    """Summary generation errors surface in summary_errors (from the L3 helper), not raised."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_episodes = AsyncMock(return_value=[{"episode_id": "ep_fail"}])
    l3 = MagicMock()
    l3.generate_missing_episodic_summaries = AsyncMock(
        return_value={"generated": 0, "errors": ["ep_fail: LLM timeout"]}
    )
    l1 = MagicMock()
    unified = MagicMock(); unified.l2 = l2; unified.l3 = l3; unified.l1 = l1

    with (
        build_patcher(unified),
        _patched_l2_maintenance_lock(),
        patch(
            "magi.memory.l2.episode_formation.consolidate_episodes",
            new=AsyncMock(return_value=MagicMock(
                promoted=0, standouts=1, merged=0, invalidated=0, promoted_episode_ids=[],
            )),
        ),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 200
    body = r.json()
    assert body["summaries_generated"] == 0
    assert len(body["summary_errors"]) == 1
    assert "ep_fail" in body["summary_errors"][0]


def test_reconsolidate_no_generation_when_l3_missing(app_with_mock_memory):
    """When L3 is unavailable, consolidation still runs and no summaries are generated."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_episodes = AsyncMock(return_value=[{"episode_id": "ep1"}])
    unified = MagicMock(); unified.l2 = l2; unified.l3 = None; unified.l1 = None

    with (
        build_patcher(unified),
        _patched_l2_maintenance_lock(),
        patch(
            "magi.memory.l2.episode_formation.consolidate_episodes",
            new=AsyncMock(return_value=MagicMock(
                promoted=1, standouts=0, merged=0, invalidated=0, promoted_episode_ids=["ep1"],
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


def test_reconsolidate_returns_409_when_l2_maintenance_running(
    app_with_mock_memory,
    runtime_paths_with_schema,
):
    """Manual reconsolidate shares the L2 maintenance target lock."""
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
            ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            TARGET_KEY_L2_MAINTENANCE,
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
            "magi.api.routers.memory.l2.episodes_routes.get_runtime_paths",
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
    unified = MagicMock(); unified.l2 = None
    with build_patcher(unified):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 503
