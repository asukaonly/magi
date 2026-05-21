"""Integration tests for /memory/l2/episodes surface + reconsolidate."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.router import memory_router


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


def test_list_episodes_default_surface_unchanged(app_with_mock_memory):
    """Without surface=standout, default behavior is intact."""
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
    l2.list_standout_episodes.assert_not_called()


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


def test_reconsolidate_runs_consolidate_and_generates_missing_summaries(app_with_mock_memory):
    """Reconsolidate: consolidate, then generate L3 summary for each standout missing one."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_standout_episodes = AsyncMock(return_value=[
        {"episode_id": "ep_has",  "primary_entity_ids": [], "time_start": 0, "time_end": 100},
        {"episode_id": "ep_need", "primary_entity_ids": [], "time_start": 100, "time_end": 200},
    ])
    l2.list_episode_events = AsyncMock(return_value=[{"event_id": "evt1"}])
    l3 = MagicMock()
    # ep_has already has summary; ep_need doesn't
    l3.get_episodic_summary_by_episode_id = AsyncMock(
        side_effect=lambda eid: {"summary_id": "x"} if eid == "ep_has" else None
    )
    l3.generate_episodic_summary = AsyncMock(return_value={"summary_id": "newly_generated"})
    l1 = MagicMock()
    unified = MagicMock(); unified.l2 = l2; unified.l3 = l3; unified.l1 = l1

    # consolidate_episodes is invoked from within the route; patch where it's imported.
    with build_patcher(unified), patch(
        "magi.memory.l2.episode_formation.consolidate_episodes",
        new=AsyncMock(return_value=MagicMock(promoted=2, standouts=1, merged=0, invalidated=0)),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 200
    body = r.json()
    assert body["promoted"] == 2
    assert body["standouts"] == 1
    assert body["summaries_generated"] == 1  # only ep_need got generated
    assert body["summary_errors"] == []
    l3.generate_episodic_summary.assert_awaited_once()
    call_kwargs = l3.generate_episodic_summary.await_args.kwargs
    assert call_kwargs["episode_event_ids"] == ["evt1"]


def test_reconsolidate_skips_summary_when_no_events(app_with_mock_memory):
    """Episodes with no event memberships are skipped for summary generation."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_standout_episodes = AsyncMock(return_value=[
        {"episode_id": "ep_empty", "primary_entity_ids": [], "time_start": 0, "time_end": 100},
    ])
    l2.list_episode_events = AsyncMock(return_value=[])  # no events
    l3 = MagicMock()
    l3.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    l3.generate_episodic_summary = AsyncMock()
    l1 = MagicMock()
    unified = MagicMock(); unified.l2 = l2; unified.l3 = l3; unified.l1 = l1

    with build_patcher(unified), patch(
        "magi.memory.l2.episode_formation.consolidate_episodes",
        new=AsyncMock(return_value=MagicMock(promoted=0, standouts=0, merged=0, invalidated=0)),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 200
    body = r.json()
    assert body["summaries_generated"] == 0
    l3.generate_episodic_summary.assert_not_awaited()


def test_reconsolidate_captures_summary_errors(app_with_mock_memory):
    """Summary generation errors are captured in summary_errors list, not raised."""
    app, build_patcher = app_with_mock_memory
    l2 = MagicMock()
    l2.list_standout_episodes = AsyncMock(return_value=[
        {"episode_id": "ep_fail", "primary_entity_ids": [], "time_start": 0, "time_end": 100},
    ])
    l2.list_episode_events = AsyncMock(return_value=[{"event_id": "evt1"}])
    l3 = MagicMock()
    l3.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    l3.generate_episodic_summary = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    l1 = MagicMock()
    unified = MagicMock(); unified.l2 = l2; unified.l3 = l3; unified.l1 = l1

    with build_patcher(unified), patch(
        "magi.memory.l2.episode_formation.consolidate_episodes",
        new=AsyncMock(return_value=MagicMock(promoted=0, standouts=1, merged=0, invalidated=0)),
    ):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 200
    body = r.json()
    assert body["summaries_generated"] == 0
    assert len(body["summary_errors"]) == 1
    assert "ep_fail" in body["summary_errors"][0]


def test_reconsolidate_503_when_l2_missing(app_with_mock_memory):
    """Returns 503 when L2 store is not initialized."""
    app, build_patcher = app_with_mock_memory
    unified = MagicMock(); unified.l2 = None
    with build_patcher(unified):
        client = TestClient(app)
        r = client.post("/api/memory/l2/episodes/reconsolidate")
    assert r.status_code == 503
