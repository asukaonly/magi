"""Tests for evidence-grounded guided experience organization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import json

import pytest


def test_draft_chapter_and_preview_include_source_event_count():
    from magi.memory.l2.experiences.draft_organizer import (
        _chapter_from_episode,
        _episode_preview,
    )

    episode = {
        "episode_id": "ep-umi",
        "label": "software:gemini.",
        "summary": json.dumps(
            {
                "label": "查询海胆日文与 Umi",
                "content": "在 Google 和 Gemini 间搜索海胆的日文写法。",
                "key_topics": ["海胆"],
            },
            ensure_ascii=False,
        ),
        "time_start": 100.0,
        "time_end": 200.0,
        "source_event_count": 7,
    }
    chapter = _chapter_from_episode(episode, position=0)
    preview = _episode_preview(episode)

    assert chapter["title"] == "查询海胆日文与 Umi"
    assert chapter["summary"] == "在 Google 和 Gemini 间搜索海胆的日文写法。"
    assert chapter["event_count"] == 7
    assert preview["event_count"] == 7
    assert "key_topics" not in chapter["summary"]


def test_draft_chapter_recovers_readable_fields_from_truncated_summary():
    from magi.memory.l2.experiences.draft_organizer import _chapter_from_episode

    chapter = _chapter_from_episode(
        {
            "episode_id": "ep-umi",
            "label": "software:gemini.",
            "summary": (
                '{"label":"查询海胆日文与 Umi",'
                '"content":"在 Google 和 Gemini 间搜索海胆的日文写法。",'
                '"key_entities":[{"id":"gemini'
            ),
            "time_start": 100.0,
            "time_end": 200.0,
        },
        position=0,
    )

    assert chapter["title"] == "查询海胆日文与 Umi"
    assert chapter["summary"] == "在 Google 和 Gemini 间搜索海胆的日文写法。"


@pytest.mark.asyncio
async def test_organizer_uses_original_query_and_persists_validated_selection():
    from magi.memory.l2.experiences.draft_organizer import organize_experience_draft

    l1 = MagicMock()
    l1.search_events = AsyncMock(return_value=[
        {
            "event_id": "evt-ticket",
            "timestamp": 120.0,
            "content": "比较东京到京都的新干线车票",
            "source": "chrome_history",
        }
    ])
    l2 = MagicMock()
    l2.find_episode_for_event = AsyncMock(return_value={
        "episode_id": "ep-train",
        "status": "active",
        "label": "准备日本旅行的车票",
        "summary": "比较新干线车票并确定东京到京都的路线。",
        "time_start": 100.0,
        "time_end": 180.0,
        "source_event_count": 5,
        "primary_entity_ids": ["place:japan"],
        "primary_place_ids": ["place:tokyo", "place:kyoto"],
        "primary_topic_keys": ["travel"],
    })
    l2.list_episodes = AsyncMock(return_value=[
        l2.find_episode_for_event.return_value,
        {
            "episode_id": "ep-minecraft",
            "status": "active",
            "label": "看红石矿车视频",
            "summary": "观看 Minecraft 红石矿车教程。",
            "time_start": 130.0,
            "time_end": 150.0,
            "source_event_count": 3,
            "primary_entity_ids": ["game:minecraft"],
            "primary_place_ids": [],
            "primary_topic_keys": ["minecraft"],
        },
    ])
    l2.create_experience_draft = AsyncMock(return_value="draft-japan")
    l2.get_experience_draft = AsyncMock(return_value={
        "draft_id": "draft-japan",
        "status": "editing",
        "query_text": "日本旅行",
        "title": "日本旅行",
        "one_sentence_review": "把东京到京都的新干线路线定下来。",
        "time_start": 100.0,
        "time_end": 180.0,
        "chapters": [],
        "possible_evidence": [],
        "excluded_evidence": [],
        "created_experience_id": None,
        "created_at": 1.0,
        "updated_at": 1.0,
    })
    selector = MagicMock()
    selector.select = AsyncMock(return_value={
        "is_experience": True,
        "title": "日本旅行",
        "one_sentence_review": "把东京到京都的新干线路线定下来。",
        "included_episode_ids": ["ep-train"],
        "included_event_ids": [],
        "excluded_refs": [
            {"ref_type": "episode", "ref_id": "ep-minecraft", "reason": "不同主题"}
        ],
        "time_start": 100.0,
        "time_end": 180.0,
        "confidence": 0.9,
        "reason": "证据一致",
        "primary_entity_ids": ["place:japan"],
        "primary_place_ids": ["place:tokyo", "place:kyoto"],
        "primary_topic_keys": ["travel"],
    })
    unified = MagicMock(l1=l1, l2=l2, scenario_llm_pool=None)

    result = await organize_experience_draft(
        unified,
        query_text="日本旅行",
        time_start=90.0,
        time_end=200.0,
        selector=selector,
    )

    assert result["status"] == "draft"
    l1.search_events.assert_awaited_once_with(query="日本旅行", limit=40)
    l2.list_episodes.assert_awaited_once_with(
        status="active", time_start=90.0, time_end=200.0, limit=100
    )
    create_kwargs = l2.create_experience_draft.await_args.kwargs
    assert create_kwargs["chapters"][0]["episode_ids"] == ["ep-train"]
    assert create_kwargs["chapters"][0]["event_count"] == 5
    assert create_kwargs["possible_evidence"] == []
    assert create_kwargs["excluded_evidence"][0]["ref_id"] == "ep-minecraft"
    assert create_kwargs["excluded_evidence"][0]["event_count"] == 3


@pytest.mark.asyncio
async def test_organizer_requests_period_choice_for_distant_matching_islands():
    from magi.memory.l2.experiences.draft_organizer import organize_experience_draft

    month = 31 * 24 * 60 * 60
    l1 = MagicMock()
    l1.search_events = AsyncMock(return_value=[
        {"event_id": "a1", "timestamp": 100.0, "content": "日本旅行 东京"},
        {"event_id": "a2", "timestamp": 200.0, "content": "日本旅行 京都"},
        {"event_id": "b1", "timestamp": month, "content": "日本旅行 大阪"},
        {"event_id": "b2", "timestamp": month + 100.0, "content": "日本旅行 奈良"},
    ])
    l2 = MagicMock()
    l2.create_experience_draft = AsyncMock()
    unified = MagicMock(l1=l1, l2=l2, scenario_llm_pool=None)

    result = await organize_experience_draft(unified, query_text="日本旅行")

    assert result["status"] == "ambiguous"
    assert len(result["choices"]) == 2
    l2.create_experience_draft.assert_not_awaited()
