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
    l3.list_summaries_by_category = AsyncMock(
        side_effect=lambda **kwargs: (
            list(insights or [])
            if "state_change" in kwargs["summary_categories"]
            else list(temporal or [])
        )
    )
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
    insights = [
        {
            "summary_id": "ins-1",
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "你最近转向更安静的播放选择",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "pending_confirmation",
            "source_event_count": 8,
        }
    ]
    temporal = [
        {
            "summary_id": "tmp-1",
            "summary_type": "temporal",
            "summary_category": "week",
            "content": "本周以阅读为主",
            "essence_prose": "本周重点是阅读。",
            "period_end": 200.0,
            "updated_at": 200.0,
            "review_state": "neutral",
            "source_event_count": 14,
        }
    ]
    unified = _stub_memory(insights=insights, temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    assert [item["summary_id"] for item in body["items"]] == ["ins-1", "tmp-1"]
    assert body["items"][0]["review_state"] == "pending_confirmation"
    assert body["items"][0]["evidence_event_count"] == 8
    assert body["items"][0]["feed_group"] == "memory_update"
    assert body["items"][0]["summary_feed_visible"] is False
    assert body["items"][1]["essence_prose"] == "本周重点是阅读。"
    assert body["items"][1]["feed_group"] == "periodic"
    assert body["items"][1]["summary_feed_visible"] is True
    assert body["items"][1]["featured_rank"] == 0
    assert body["items"][1]["preview_text"] == "本周重点是阅读。"
    assert body["stats"] == {
        "highlights": 0,
        "periodic": 1,
        "observations": 0,
        "tasks": 0,
    }


def test_legacy_temporal_summary_gets_a_compact_plain_preview(app_factory):
    temporal = [
        {
            "summary_id": "legacy-week",
            "summary_type": "temporal",
            "summary_category": "week",
            "content": (
                "## 要点\n"
                "- 浏览重心转向 **AI 行业动态**。\n"
                "- 查阅 `magi-plugins` 仓库并处理通知。\n\n"
                "## 时间线\n"
                "- 这段完整内容只应该出现在详情里。"
            ),
            "period_end": 200.0,
            "updated_at": 200.0,
            "review_state": "neutral",
            "source_event_count": 14,
        }
    ]
    unified = _stub_memory(insights=[], temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})

    body = resp.json()
    item = body["items"][0]
    assert item["preview_text"] == (
        "浏览重心转向 AI 行业动态。 查阅 magi-plugins 仓库并处理通知。"
    )
    assert "##" not in item["preview_text"]
    assert "这段完整内容只应该出现在详情里" not in item["preview_text"]
    assert "这段完整内容只应该出现在详情里" in item["content"]


def test_pagination_limits_results(app_factory):
    temporal = [
        {
            "summary_id": f"t-{i}",
            "summary_type": "temporal",
            "summary_category": "day",
            "content": "",
            "period_end": float(i),
            "updated_at": float(i),
            "review_state": "neutral",
            "source_event_count": 1,
        }
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


def test_summary_surface_and_group_filter_are_server_owned(app_factory):
    insights = [
        {
            "summary_id": "state-1",
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "待确认记忆",
            "period_end": 400.0,
            "updated_at": 400.0,
            "review_state": "pending_confirmation",
            "source_event_count": 2,
        },
        {
            "summary_id": "trend-1",
            "summary_type": "insight",
            "summary_category": "trend_shift",
            "content": "长期观察",
            "period_end": 300.0,
            "updated_at": 300.0,
            "review_state": "neutral",
            "source_event_count": 3,
        },
        {
            "summary_id": "task-1",
            "summary_type": "insight",
            "summary_category": "task_reflection",
            "content": "任务复盘",
            "period_end": 200.0,
            "updated_at": 200.0,
            "review_state": "neutral",
            "source_event_count": 4,
        },
    ]
    temporal = [
        {
            "summary_id": "day-1",
            "summary_type": "temporal",
            "summary_category": "day",
            "content": "时段总结",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 5,
        },
    ]
    unified = _stub_memory(insights=insights, temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get(
            "/api/memory/stories",
            params={"surface": "summary", "group": "tasks", "limit": 20},
        )
    body = resp.json()
    assert [item["summary_id"] for item in body["items"]] == ["task-1"]
    assert body["total"] == 1
    assert body["items"][0]["feed_group"] == "tasks"
    assert body["stats"] == {
        "highlights": 2,
        "periodic": 1,
        "observations": 1,
        "tasks": 1,
    }


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
        summary_id="sum-1",
        review_state="confirmed",
        user_note="yes",
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


def test_evidence_insight_uses_source_event_ids(app_factory):
    """For insight summaries, evidence comes from source_event_ids list."""
    l3 = MagicMock()
    l3.get_summary_by_id = AsyncMock(
        return_value={
            "summary_id": "ins-1",
            "summary_type": "insight",
            "summary_category": "state_change",
            "source_event_ids": ["evt-a", "evt-b"],
            "period_start": 100.0,
            "period_end": 200.0,
        }
    )
    l1 = MagicMock()
    l1.get_event = AsyncMock(
        side_effect=[
            {
                "event_id": "evt-a",
                "timestamp": 100.0,
                "source": "chat",
                "event_type": "user_message",
                "memory_domain": "user_authored",
                "content": "I slept badly",
            },
            {
                "event_id": "evt-b",
                "timestamp": 150.0,
                "source": "chat",
                "event_type": "user_message",
                "memory_domain": "user_authored",
                "content": "mosquito kept biting",
            },
        ]
    )
    unified = MagicMock()
    unified.l3 = l3
    unified.l1 = l1
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories/ins-1/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "source_ids"
    assert [it["event_id"] for it in body["items"]] == ["evt-a", "evt-b"]
    assert body["items"][0]["content"] == "I slept badly"
    l1.get_event.assert_any_await("evt-a")
    l1.get_event.assert_any_await("evt-b")


def test_evidence_temporal_uses_time_window(app_factory):
    """Temporal summaries fall back to the L1 window when no source ids exist."""
    l3 = MagicMock()
    l3.get_summary_by_id = AsyncMock(
        return_value={
            "summary_id": "day-1",
            "summary_type": "temporal",
            "summary_category": "day",
            "source_event_ids": [],
            "period_start": 1700000000.0,
            "period_end": 1700086400.0,
        }
    )
    l1 = MagicMock()
    l1.query_events = AsyncMock(
        return_value=[
            {
                "event_id": "e1",
                "timestamp": 1700010000.0,
                "source": "chrome_history",
                "event_type": "SENSOR_EVENT",
                "memory_domain": "external_activity",
                "content": "visited example.com",
            },
        ]
    )
    unified = MagicMock()
    unified.l3 = l3
    unified.l1 = l1
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories/day-1/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "time_window"
    assert len(body["items"]) == 1
    assert body["items"][0]["event_id"] == "e1"
    l1.query_events.assert_awaited_once()
    call_kwargs = l1.query_events.await_args.kwargs
    assert call_kwargs["start_time"] == 1700000000.0
    assert call_kwargs["end_time"] == 1700086400.0
    assert call_kwargs["cognition_eligible"] is True
    assert call_kwargs["order_by"] == "timestamp_desc"
    assert call_kwargs["include_embedding_fields"] is False


def test_evidence_temporal_prefers_source_event_ids(app_factory):
    """Temporal summaries expose the representative evidence used at generation time."""
    l3 = MagicMock()
    l3.get_summary_by_id = AsyncMock(
        return_value={
            "summary_id": "week-1",
            "summary_type": "temporal",
            "summary_category": "week",
            "source_event_ids": ["evt-a", "evt-b"],
            "period_start": 1700000000.0,
            "period_end": 1700604800.0,
        }
    )
    l1 = MagicMock()
    l1.get_event = AsyncMock(
        side_effect=[
            {
                "event_id": "evt-a",
                "timestamp": 1700010000.0,
                "source": "terminal-history",
                "event_type": "SENSOR_EVENT",
                "memory_domain": "external_activity",
                "content": "fixed CI",
            },
            {
                "event_id": "evt-b",
                "timestamp": 1700020000.0,
                "source": "chrome_history",
                "event_type": "SENSOR_EVENT",
                "memory_domain": "external_activity",
                "content": "read model notes",
            },
        ]
    )
    l1.query_events = AsyncMock(return_value=[])
    unified = MagicMock()
    unified.l3 = l3
    unified.l1 = l1
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories/week-1/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "source_ids"
    assert [it["event_id"] for it in body["items"]] == ["evt-a", "evt-b"]
    l1.get_event.assert_any_await("evt-a")
    l1.get_event.assert_any_await("evt-b")
    l1.query_events.assert_not_awaited()


def test_evidence_404_for_missing_summary(app_factory):
    l3 = MagicMock()
    l3.get_summary_by_id = AsyncMock(return_value=None)
    unified = MagicMock()
    unified.l3 = l3
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories/nope/evidence")
    assert resp.status_code == 404


def test_legible_filter_hides_insights_with_raw_trait_name(app_factory):
    """Legacy insight rows containing raw trait_name (e.g. 'state.sleep_quality')
    are filtered at retrieval — they don't reach the user."""
    insights = [
        {
            "summary_id": "leak",
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "用户状态有更新：state.sleep_quality 更明确：poor",  # leaks raw trait_name
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 1,
        },
        {
            "summary_id": "clean",
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "你的状态：睡眠较差",  # clean
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 1,
        },
    ]
    unified = _stub_memory(insights=insights, temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    ids = [item["summary_id"] for item in body["items"]]
    assert "clean" in ids
    assert "leak" not in ids


def test_story_feed_keeps_latest_interest_trend_per_entity(app_factory):
    insights = [
        {
            "summary_id": "old-interest",
            "summary_type": "insight",
            "summary_category": "trend_shift",
            "content": "Recurring interested_in signal for Codex；Recurring interested_in signal for DeepSeek。",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "pending_confirmation",
            "source_event_count": 20,
            "insight_metadata": {
                "kind": "trend_shift",
                "entity_id": "user:self",
                "outcomes": [
                    {
                        "trait_name": "interest.codex-coding-tools-by-openai",
                        "winning_value": "Codex",
                    },
                    {"trait_name": "interest.deepseek", "winning_value": "DeepSeek"},
                ],
            },
        },
        {
            "summary_id": "new-interest",
            "summary_type": "insight",
            "summary_category": "trend_shift",
            "content": "最近持续关注：Codex、DeepSeek、GLM。",
            "period_end": 200.0,
            "updated_at": 200.0,
            "review_state": "pending_confirmation",
            "source_event_count": 32,
            "insight_metadata": {
                "kind": "trend_shift",
                "entity_id": "user:self",
                "outcomes": [
                    {
                        "trait_name": "interest.codex-coding-tools-by-openai",
                        "winning_value": "Codex",
                    },
                    {"trait_name": "interest.deepseek", "winning_value": "DeepSeek"},
                    {"trait_name": "interest.glm-5-2", "winning_value": "GLM-5.2"},
                ],
            },
        },
        {
            "summary_id": "stress-trend",
            "summary_type": "insight",
            "summary_category": "trend_shift",
            "content": "你的压力水平持续偏高。",
            "period_end": 150.0,
            "updated_at": 150.0,
            "review_state": "pending_confirmation",
            "source_event_count": 5,
            "insight_metadata": {
                "kind": "trend_shift",
                "entity_id": "user:self",
                "outcomes": [
                    {"trait_name": "stress_level", "winning_value": "high"},
                ],
            },
        },
    ]
    unified = _stub_memory(insights=insights, temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    ids = [item["summary_id"] for item in body["items"]]
    assert "new-interest" in ids
    assert "stress-trend" in ids
    assert "old-interest" not in ids


def test_story_feed_projects_legacy_interest_trend_as_readable_summary(app_factory):
    insights = [
        {
            "summary_id": "legacy-interest",
            "summary_type": "insight",
            "summary_category": "trend_shift",
            "content": "Recurring interested_in signal for Codex；Recurring interested_in signal for DeepSeek。",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "pending_confirmation",
            "source_event_count": 20,
            "insight_metadata": {
                "kind": "trend_shift",
                "entity_id": "user:self",
                "outcomes": [
                    {
                        "trait_name": "interest.codex-coding-tools-by-openai",
                        "winning_value": "Codex",
                    },
                    {"trait_name": "interest.deepseek", "winning_value": "DeepSeek"},
                ],
            },
        },
    ]
    unified = _stub_memory(insights=insights, temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    assert body["items"][0]["summary_id"] == "legacy-interest"
    assert "Recurring" not in body["items"][0]["content"]
    assert "interested_in" not in body["items"][0]["content"]
    assert "Codex" in body["items"][0]["content"]
    assert "DeepSeek" in body["items"][0]["content"]


def test_story_feed_drops_raw_legacy_interest_title(app_factory):
    insights = [
        {
            "summary_id": "legacy-interest",
            "summary_type": "insight",
            "summary_category": "trend_shift",
            "title": "Recurring interested_in signal for Codex; Recurring interested_in signal for DeepSeek.",
            "content": "Recurring interested_in signal for Codex; Recurring interested_in signal for DeepSeek.",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "pending_confirmation",
            "source_event_count": 20,
            "insight_metadata": {
                "kind": "trend_shift",
                "entity_id": "user:self",
                "outcomes": [
                    {
                        "trait_name": "interest.codex-coding-tools-by-openai",
                        "winning_value": "Codex",
                    },
                    {"trait_name": "interest.deepseek", "winning_value": "DeepSeek"},
                ],
            },
        },
    ]
    unified = _stub_memory(insights=insights, temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    assert body["items"][0]["title"] == ""
    assert "Recurring" not in body["items"][0]["content"]
    assert "interested_in" not in body["items"][0]["content"]
    assert body["items"][0]["content"] == "最近持续关注：Codex、DeepSeek。"


def test_story_feed_projects_legacy_interest_state_change_as_readable_summary(app_factory):
    insights = [
        {
            "summary_id": "legacy-state-interest",
            "summary_type": "insight",
            "summary_category": "state_change",
            "title": "Recurring interested_in signal for Codex; Recurring interested_in signal for DeepSeek.",
            "content": "Recurring interested_in signal for Codex; Recurring interested_in signal for DeepSeek.",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "pending_confirmation",
            "source_event_count": 20,
            "insight_metadata": {
                "kind": "state_change",
                "entity_id": "user:self",
                "outcomes": [
                    {
                        "trait_name": "interest.codex-coding-tools-by-openai",
                        "winning_value": "Codex",
                    },
                    {"trait_name": "interest.deepseek", "winning_value": "DeepSeek"},
                ],
            },
        },
    ]
    unified = _stub_memory(insights=insights, temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    assert body["items"][0]["summary_id"] == "legacy-state-interest"
    assert body["items"][0]["title"] == ""
    assert "Recurring" not in body["items"][0]["content"]
    assert "interested_in" not in body["items"][0]["content"]
    assert body["items"][0]["content"] == "最近持续关注：Codex、DeepSeek。"


def test_legible_filter_allows_file_paths_and_urls(app_factory):
    """Common file extensions and TLDs are not flagged as trait_name leaks."""
    insights = [
        {
            "summary_id": "url",
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "你访问了 v2ex.com 和编辑了 main.py。",  # safe TLD + file ext
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 1,
        },
    ]
    unified = _stub_memory(insights=insights, temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    ids = [item["summary_id"] for item in body["items"]]
    assert "url" in ids


def test_legible_filter_does_not_touch_temporal_summaries(app_factory):
    """Temporal day/week/month summaries aren't subject to the trait-leak filter."""
    temporal = [
        {
            "summary_id": "day1",
            "summary_type": "temporal",
            "summary_category": "day",
            "content": "你在 main.go 和 main.py 之间切换",  # would trip filter if applied
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 5,
        },
    ]
    unified = _stub_memory(insights=[], temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    assert [item["summary_id"] for item in body["items"]] == ["day1"]


def test_story_feed_hides_rule_fallback_temporal_summaries(app_factory):
    temporal = [
        {
            "summary_id": "rule-day",
            "summary_type": "temporal",
            "summary_category": "day",
            "content": "这一天的记忆主要围绕浏览记录展开。",
            "period_end": 200.0,
            "updated_at": 200.0,
            "review_state": "neutral",
            "source_event_count": 120,
            "generated_by_model": "rule-summary",
        },
        {
            "summary_id": "llm-day",
            "summary_type": "temporal",
            "summary_category": "day",
            "content": "这一天主要在调整 Magi 的总结生成，让正文先稳定可读。",
            "period_end": 100.0,
            "updated_at": 100.0,
            "review_state": "neutral",
            "source_event_count": 12,
            "generated_by_model": "temporal-llm",
        },
    ]
    unified = _stub_memory(insights=[], temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    ids = [item["summary_id"] for item in body["items"]]
    assert "llm-day" in ids
    assert "rule-day" not in ids
