"""Integration tests for /api/memory/stories."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.stories_routes import build_router, override_unified_memory_for_test


@pytest.fixture
def app_factory():
    def _build():
        app = FastAPI()
        app.include_router(build_router(), prefix="/api/memory")
        return app
    return _build


def _stub_memory(insights=None, temporal=None):
    l3 = MagicMock()
    l3.list_summaries_by_category = AsyncMock(side_effect=lambda **kwargs: (
        list(insights or []) if "state_change" in kwargs["summary_categories"]
        else list(temporal or [])
    ))
    unified = MagicMock()
    unified.l3 = l3
    return unified


def test_empty_store_returns_empty_feed(app_factory):
    unified = _stub_memory(insights=[], temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_proposed_insights_float_to_top(app_factory):
    insights = [{
        "summary_id": "ins-1",
        "summary_type": "insight",
        "summary_category": "state_change",
        "content": "你最近转向更安静的播放选择",
        "period_end": 100.0,
        "updated_at": 100.0,
        "review_state": "pending_confirmation",
        "source_event_count": 8,
    }]
    temporal = [{
        "summary_id": "tmp-1",
        "summary_type": "temporal",
        "summary_category": "week",
        "content": "本周以阅读为主",
        "period_end": 200.0,
        "updated_at": 200.0,
        "review_state": "neutral",
        "source_event_count": 14,
    }]
    unified = _stub_memory(insights=insights, temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    assert [item["summary_id"] for item in body["items"]] == ["ins-1", "tmp-1"]
    assert body["items"][0]["review_state"] == "pending_confirmation"
    assert body["items"][0]["evidence_event_count"] == 8


def test_pagination_limits_results(app_factory):
    temporal = [
        {"summary_id": f"t-{i}", "summary_type": "temporal", "summary_category": "day",
         "content": "", "period_end": float(i), "updated_at": float(i),
         "review_state": "neutral", "source_event_count": 1}
        for i in range(5)
    ]
    unified = _stub_memory(insights=[], temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 2, "offset": 1})
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["summary_id"] == "t-3"  # second-newest after offset 1
    assert body["total"] == 5


def test_review_state_patch_updates_summary(app_factory):
    l3 = MagicMock()
    l3.set_review_state = AsyncMock(return_value=True)
    unified = MagicMock()
    unified.l3 = l3
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.patch(
            "/api/memory/stories/sum-1/review",
            json={"review_state": "confirmed", "user_note": "yes"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["summary_id"] == "sum-1"
    assert body["review_state"] == "confirmed"
    l3.set_review_state.assert_awaited_once_with(
        summary_id="sum-1", review_state="confirmed", user_note="yes",
    )


def test_review_state_patch_404_for_unknown(app_factory):
    l3 = MagicMock()
    l3.set_review_state = AsyncMock(return_value=False)
    unified = MagicMock()
    unified.l3 = l3
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.patch(
            "/api/memory/stories/nope/review",
            json={"review_state": "confirmed"},
        )
    assert resp.status_code == 404


def test_review_state_patch_rejects_invalid_state(app_factory):
    unified = MagicMock()
    unified.l3 = MagicMock()
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.patch(
            "/api/memory/stories/sum-1/review",
            json={"review_state": "bogus"},
        )
    assert resp.status_code == 422


def test_expired_state_change_insight_filtered_out(app_factory):
    """state_change insights past their salience_until are hidden."""
    insights = [
        {
            "summary_id": "stale",
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "old state",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 1,
            "insight_metadata": {"salience_until": 50.0},  # well in the past
        },
        {
            "summary_id": "fresh",
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "current state",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 1,
            "insight_metadata": {"salience_until": 9999999999.0},  # far future
        },
        {
            "summary_id": "no_expiry",
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "permanent state",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 1,
            "insight_metadata": {"salience_until": None},
        },
    ]
    unified = _stub_memory(insights=insights, temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    ids = [item["summary_id"] for item in body["items"]]
    assert "stale" not in ids
    assert "fresh" in ids
    assert "no_expiry" in ids
