"""Tests for guided experience draft persistence and promotion."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_experience_draft_round_trip_and_update(l2_store_with_schema):
    store = l2_store_with_schema
    draft_id = await store.create_experience_draft(
        draft_id="draft-japan",
        query_text="2026年5月1日到10日 日本旅行",
        title="日本旅行",
        one_sentence_review="从东京到京都和奈良的一段旅行。",
        time_start=100.0,
        time_end=500.0,
        chapters=[
            {
                "chapter_id": "chapter-1",
                "title": "出发前的准备",
                "summary": "整理车票和住宿。",
                "time_start": 100.0,
                "time_end": 200.0,
                "episode_ids": ["ep-train"],
                "event_ids": ["evt-ticket"],
            }
        ],
        possible_evidence=[
            {
                "ref_type": "episode",
                "ref_id": "ep-camera",
                "title": "挑选相机",
                "summary": "可能和旅行有关。",
                "time_start": 210.0,
                "time_end": 240.0,
            }
        ],
    )

    assert draft_id == "draft-japan"
    draft = await store.get_experience_draft(draft_id=draft_id)
    assert draft is not None
    assert draft["status"] == "editing"
    assert draft["chapters"][0]["episode_ids"] == ["ep-train"]
    assert draft["possible_evidence"][0]["ref_id"] == "ep-camera"

    updated = await store.update_experience_draft(
        draft_id=draft_id,
        title="第一次日本旅行",
        one_sentence_review="一段从出发准备到返程都完整留下来的旅行。",
    )
    assert updated is True
    drafts = await store.list_experience_drafts(status="editing")
    assert [item["draft_id"] for item in drafts] == [draft_id]
    assert drafts[0]["title"] == "第一次日本旅行"


@pytest.mark.asyncio
async def test_experience_draft_update_rejects_stale_expected_timestamp(l2_store_with_schema):
    store = l2_store_with_schema
    await store.create_experience_draft(
        draft_id="draft-versioned",
        query_text="Versioned draft",
        title="Initial title",
        one_sentence_review="Initial recap",
        time_start=100.0,
        time_end=200.0,
        chapters=[],
        possible_evidence=[],
    )
    initial = await store.get_experience_draft(draft_id="draft-versioned")
    assert initial is not None
    await store.update_experience_draft(
        draft_id="draft-versioned",
        title="Concurrent title",
    )

    updated = await store.update_experience_draft(
        draft_id="draft-versioned",
        expected_updated_at=initial["updated_at"],
        title="Stale title",
    )

    assert updated is False
    current = await store.get_experience_draft(draft_id="draft-versioned")
    assert current is not None
    assert current["title"] == "Concurrent title"


@pytest.mark.asyncio
async def test_create_experience_from_draft_preserves_chapters(l2_store_with_schema):
    from magi.memory.l2.experiences.draft_creation import create_experience_from_draft

    store = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-train",
        status="active",
        label="准备新干线车票",
        time_start=100.0,
        time_end=200.0,
        source_event_count=3,
    )
    await store.create_experience_draft(
        draft_id="draft-japan",
        query_text="日本旅行",
        title="第一次日本旅行",
        one_sentence_review="从东京走到京都的一段旅行。",
        time_start=100.0,
        time_end=200.0,
        chapters=[
            {
                "chapter_id": "chapter-1",
                "title": "出发准备",
                "summary": "把路线和车票定下来。",
                "time_start": 100.0,
                "time_end": 200.0,
                "episode_ids": ["ep-train"],
                "event_ids": [],
            }
        ],
        possible_evidence=[],
    )

    experience_id = await create_experience_from_draft(store, draft_id="draft-japan")

    experience = await store.get_experience(experience_id=experience_id)
    assert experience is not None
    assert experience["status"] == "active"
    assert experience["title"] == "第一次日本旅行"
    assert experience["chapters"][0]["title"] == "出发准备"
    members = await store.list_experience_members(experience_id=experience_id)
    assert [(item["member_type"], item["member_id"]) for item in members] == [
        ("episode", "ep-train")
    ]
    draft = await store.get_experience_draft(draft_id="draft-japan")
    assert draft is not None
    assert draft["status"] == "completed"
    assert draft["created_experience_id"] == experience_id

    retry_experience_id = await create_experience_from_draft(
        store,
        draft_id="draft-japan",
    )
    assert retry_experience_id == experience_id
