"""Tests for guided experience draft persistence and promotion."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_experience_draft_round_trip_and_update(l2_store_with_schema):
    store = l2_store_with_schema
    for episode_id in ("ep-train", "ep-camera"):
        await store.create_episode(
            episode_id=episode_id,
            status="active",
            time_start=100.0,
            time_end=500.0,
        )
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
    assert draft["user_cover_asset_ref"] is None
    assert draft["chapters"][0]["episode_ids"] == ["ep-train"]
    assert draft["possible_evidence"][0]["ref_id"] == "ep-camera"

    updated = await store.update_experience_draft(
        draft_id=draft_id,
        title="第一次日本旅行",
        one_sentence_review="一段从出发准备到返程都完整留下来的旅行。",
        user_cover_asset_ref="manual-entry-asset://draft-cover.jpg",
    )
    assert updated is True
    drafts = await store.list_experience_drafts(status="editing")
    assert [item["draft_id"] for item in drafts] == [draft_id]
    assert drafts[0]["title"] == "第一次日本旅行"
    assert drafts[0]["user_cover_asset_ref"] == "manual-entry-asset://draft-cover.jpg"


@pytest.mark.asyncio
async def test_experience_draft_rejects_inactive_episode_references(l2_store_with_schema):
    store = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-active",
        status="active",
        time_start=100.0,
        time_end=200.0,
    )
    await store.create_episode(
        episode_id="ep-private",
        status="invalidated",
        time_start=100.0,
        time_end=200.0,
    )

    await store.create_experience_draft(
        draft_id="draft-active",
        query_text="Active draft",
        title="Active draft",
        one_sentence_review="Active evidence only",
        time_start=100.0,
        time_end=200.0,
        chapters=[{"episode_ids": ["ep-active"], "event_ids": []}],
        possible_evidence=[],
    )

    with pytest.raises(ValueError, match="not active"):
        await store.update_experience_draft(
            draft_id="draft-active",
            chapters=[{"episode_ids": ["ep-private"], "event_ids": []}],
        )
    draft = await store.get_experience_draft(draft_id="draft-active")
    assert draft is not None
    assert draft["chapters"][0]["episode_ids"] == ["ep-active"]

    with pytest.raises(ValueError, match="not active"):
        await store.create_experience_draft(
            draft_id="draft-private",
            query_text="Private draft",
            title="Private draft",
            one_sentence_review="Must not persist",
            time_start=100.0,
            time_end=200.0,
            chapters=[{"episode_ids": ["ep-private"], "event_ids": []}],
            possible_evidence=[],
        )
    assert await store.get_experience_draft(draft_id="draft-private") is None


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
    await store.update_experience_draft(
        draft_id="draft-japan",
        user_cover_asset_ref="manual-entry-asset://japan-cover.jpg",
    )

    experience_id = await create_experience_from_draft(store, draft_id="draft-japan")

    experience = await store.get_experience(experience_id=experience_id)
    assert experience is not None
    assert experience["status"] == "active"
    assert experience["title"] == "第一次日本旅行"
    assert experience["user_cover_asset_ref"] == "manual-entry-asset://japan-cover.jpg"
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


@pytest.mark.asyncio
async def test_create_experience_from_draft_retries_after_completion_update_failure(
    l2_store_with_schema,
    monkeypatch,
):
    from magi.memory.l2.experiences.draft_creation import create_experience_from_draft

    store = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-train",
        status="active",
        label="Prepare train tickets",
        time_start=100.0,
        time_end=200.0,
        source_event_count=2,
    )
    await store.add_episode_events(
        episode_id="ep-train",
        event_ids=["evt-ticket", "evt-route"],
    )
    await store.create_episode(
        episode_id="ep-flight",
        status="active",
        label="Book the return flight",
        time_start=300.0,
        time_end=500.0,
        source_event_count=2,
    )
    await store.add_episode_events(
        episode_id="ep-flight",
        event_ids=["evt-flight", "evt-boarding"],
    )
    await store.create_experience_draft(
        draft_id="draft-retry",
        query_text="Japan trip",
        title="First Japan trip",
        one_sentence_review="A trip from Tokyo to Kyoto.",
        time_start=100.0,
        time_end=200.0,
        chapters=[
            {
                "chapter_id": "chapter-1",
                "title": "Departure planning",
                "summary": "Finalize the route and tickets.",
                "time_start": 100.0,
                "time_end": 200.0,
                "episode_ids": ["ep-train"],
                "event_ids": ["evt-ticket"],
            }
        ],
        possible_evidence=[],
    )
    update_draft = store.update_experience_draft
    should_fail_completion = True

    async def fail_first_completion_update(*, draft_id: str, **fields):
        nonlocal should_fail_completion
        if fields.get("status") == "completed" and should_fail_completion:
            should_fail_completion = False
            raise RuntimeError("Simulated draft completion failure")
        return await update_draft(draft_id=draft_id, **fields)

    monkeypatch.setattr(store, "update_experience_draft", fail_first_completion_update)

    with pytest.raises(RuntimeError, match="Simulated draft completion failure"):
        await create_experience_from_draft(store, draft_id="draft-retry")

    experiences_after_failure = await store.list_experiences()
    assert len(experiences_after_failure) == 1
    stable_experience_id = experiences_after_failure[0]["experience_id"]
    draft_after_failure = await store.get_experience_draft(draft_id="draft-retry")
    assert draft_after_failure is not None
    assert draft_after_failure["status"] == "editing"
    await store.update_experience_draft(
        draft_id="draft-retry",
        title="Revised Japan trip",
        one_sentence_review="A shorter trip centered on the return journey.",
        time_start=300.0,
        time_end=500.0,
        user_cover_asset_ref="manual-entry-asset://revised-cover.jpg",
        chapters=[
            {
                "chapter_id": "chapter-2",
                "title": "Return journey",
                "summary": "Book the flight and hotel.",
                "time_start": 300.0,
                "time_end": 500.0,
                "episode_ids": ["ep-flight"],
                "event_ids": ["evt-hotel"],
            }
        ],
    )

    retry_experience_id = await create_experience_from_draft(
        store,
        draft_id="draft-retry",
    )

    assert retry_experience_id == stable_experience_id
    experiences_after_retry = await store.list_experiences()
    assert [item["experience_id"] for item in experiences_after_retry] == [stable_experience_id]
    experience = await store.get_experience(experience_id=stable_experience_id)
    assert experience is not None
    assert experience["title"] == "Revised Japan trip"
    assert experience["time_start"] == 300.0
    assert experience["time_end"] == 500.0
    assert experience["intent"] == "Revised Japan trip"
    assert experience["magi_interpretation"] == ("A shorter trip centered on the return journey.")
    assert experience["user_cover_asset_ref"] == "manual-entry-asset://revised-cover.jpg"
    assert experience["source_episode_count"] == 1
    assert experience["source_event_count"] == 3
    assert [chapter["chapter_id"] for chapter in experience["chapters"]] == ["chapter-2"]
    members = await store.list_experience_members(
        experience_id=stable_experience_id,
    )
    assert [(item["member_type"], item["member_id"]) for item in members] == [
        ("episode", "ep-flight"),
        ("event", "evt-hotel"),
    ]
    completed_draft = await store.get_experience_draft(draft_id="draft-retry")
    assert completed_draft is not None
    assert completed_draft["status"] == "completed"
    assert completed_draft["created_experience_id"] == stable_experience_id


@pytest.mark.asyncio
async def test_episode_forget_during_draft_creation_cannot_publish_experience(
    l2_store_with_schema,
    monkeypatch,
):
    from magi.memory.l2.experiences.draft_creation import create_experience_from_draft

    store = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-private-race",
        status="active",
        time_start=100.0,
        time_end=200.0,
    )
    await store.create_experience_draft(
        draft_id="draft-private-race",
        query_text="Private race",
        title="Private race",
        one_sentence_review="Must not survive deletion",
        time_start=100.0,
        time_end=200.0,
        chapters=[{"episode_ids": ["ep-private-race"], "event_ids": []}],
        possible_evidence=[],
    )
    replace_chapters = store.replace_experience_chapters

    async def replace_then_forget(**kwargs):
        replaced = await replace_chapters(**kwargs)
        await store.forget_episode(episode_id="ep-private-race")
        return replaced

    monkeypatch.setattr(store, "replace_experience_chapters", replace_then_forget)

    with pytest.raises(ValueError, match="Draft changed during creation"):
        await create_experience_from_draft(store, draft_id="draft-private-race")

    assert await store.list_experiences(status="active") == []
    assert await store.get_experience_draft(draft_id="draft-private-race") is None
