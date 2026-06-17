"""Integration tests for /memory/l2/experiences surface."""

from __future__ import annotations

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
        if getattr(route, "path", "").startswith("/l2/experiences")
    }

    assert ("/l2/experiences", ("GET",)) in routes
    assert ("/l2/experiences/{experience_id}", ("GET",)) in routes
    assert ("/l2/experiences/{experience_id}", ("PATCH",)) in routes
    assert ("/l2/experiences/{experience_id}/hide", ("POST",)) in routes
    assert ("/l2/experiences/{experience_id}/regenerate", ("POST",)) in routes


def test_list_experiences_returns_active_reviews(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.list_experiences = AsyncMock(return_value=[
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
    ])
    l3 = MagicMock()
    l3.get_episodic_summary_by_experience_id = AsyncMock(return_value={
        "summary_id": "sum1",
        "content": "Generated experience recap",
        "insight_metadata": {"label": "Generated experience title"},
        "updated_at": 10,
    })
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


def test_experience_detail_returns_source_episodes(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience = AsyncMock(return_value={
        "experience_id": "exp1",
        "status": "active",
        "title": "Evaluate tools",
        "time_start": 1,
        "time_end": 4,
        "primary_entity_ids": [],
        "user_label": None,
        "user_note": None,
    })
    l2.list_experience_members = AsyncMock(return_value=[
        {
            "experience_id": "exp1",
            "member_type": "episode",
            "member_id": "ep1",
            "role": "core",
            "confidence": 0.8,
            "added_at": 5,
        }
    ])
    l2.get_episode = AsyncMock(return_value={
        "episode_id": "ep1",
        "status": "active",
        "label": "Read tool docs",
        "time_start": 1,
        "time_end": 4,
        "primary_entity_ids": [],
        "user_label": None,
        "user_note": None,
    })
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


def test_annotate_experience_updates_user_fields(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.update_experience = AsyncMock(return_value=True)
    l2.get_experience = AsyncMock(return_value={
        "experience_id": "exp1",
        "status": "active",
        "title": "Generated",
        "time_start": 1,
        "time_end": 2,
        "primary_entity_ids": [],
        "user_label": "My title",
        "user_note": None,
    })
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
        user_label="My title",
        user_pinned=True,
    )
    assert response.json()["display_title"] == "My title"


def test_hide_experience_sets_hidden_status(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.update_experience = AsyncMock(return_value=True)
    l2.get_experience = AsyncMock(return_value={
        "experience_id": "exp1",
        "status": "hidden",
        "title": "Generated",
        "time_start": 1,
        "time_end": 2,
        "primary_entity_ids": [],
    })
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = None

    with build_patcher(unified):
        client = TestClient(app)
        response = client.post("/api/memory/l2/experiences/exp1/hide")

    assert response.status_code == 200
    l2.update_experience.assert_awaited_once_with(
        experience_id="exp1",
        status="hidden",
    )
    assert response.json()["status"] == "hidden"


def test_regenerate_experience_review_binds_source_experience_id(public_app_with_mock_memory):
    app, build_patcher = public_app_with_mock_memory
    l2 = MagicMock()
    l2.get_experience = AsyncMock(return_value={
        "experience_id": "exp1",
        "status": "active",
        "title": "Evaluate tools",
        "time_start": 1,
        "time_end": 2,
        "primary_entity_ids": [],
    })
    l2.list_experience_members = AsyncMock(return_value=[
        {"member_type": "episode", "member_id": "ep1", "role": "core", "confidence": 0.8}
    ])
    l2.get_episode = AsyncMock(return_value={"episode_id": "ep1", "label": "Read docs"})
    l2.list_episode_events = AsyncMock(return_value=[{"event_id": "e1"}])
    l3 = MagicMock()
    l3.generate_experience_summary = AsyncMock(return_value={
        "summary_id": "sum1",
        "content": "Generated experience recap",
        "insight_metadata": {
            "source_experience_id": "exp1",
            "label": "Generated title",
        },
        "updated_at": 5,
    })
    unified = MagicMock()
    unified.l2 = l2
    unified.l3 = l3
    unified.l1 = MagicMock()

    with build_patcher(unified):
        client = TestClient(app)
        response = client.post("/api/memory/l2/experiences/exp1/regenerate")

    assert response.status_code == 200
    l3.generate_experience_summary.assert_awaited_once()
    assert response.json()["experience_review"]["label"] == "Generated title"
    assert response.json()["experience_review"]["content"] == "Generated experience recap"
