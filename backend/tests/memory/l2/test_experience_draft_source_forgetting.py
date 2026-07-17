"""Regression coverage for source-event cleanup of experience drafts."""

from __future__ import annotations

import time

import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_source_forget_hides_episode_and_event_backed_drafts(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    await store.create_episode(
        episode_id="episode-forgotten",
        status="active",
        time_start=100.0,
        time_end=200.0,
        source_event_count=2,
    )
    await store.add_episode_events(
        episode_id="episode-forgotten",
        event_ids=["event-forgotten", "event-retained"],
    )
    await _create_draft(
        store,
        draft_id="draft-episode",
        chapters=[{"episode_ids": ["episode-forgotten"], "event_ids": []}],
    )
    await _create_draft(
        store,
        draft_id="draft-event",
        chapters=[],
        possible_evidence=[
            {
                "ref_type": "event",
                "ref_id": "event-forgotten",
                "restore_chapter": {"event_ids": ["event-forgotten"]},
            }
        ],
    )
    await _create_draft(
        store,
        draft_id="draft-unrelated",
        chapters=[{"episode_ids": [], "event_ids": ["event-unrelated"]}],
    )

    deleted = await store.forget_experience_drafts_for_source_events(
        [" event-forgotten ", "event-forgotten", ""],
    )

    assert deleted == 2
    assert await store.get_experience_draft(draft_id="draft-episode") is None
    assert await store.get_experience_draft(draft_id="draft-event") is None
    assert await store.get_experience_draft(draft_id="draft-unrelated") is not None
    assert [
        draft["draft_id"] for draft in await store.list_experience_drafts(status="editing")
    ] == ["draft-unrelated"]
    assert await store.forget_experience_drafts_for_source_events(["event-forgotten"]) == 0
    assert await store.forget_experience_drafts_for_source_events([]) == 0


@pytest.mark.asyncio
async def test_source_forget_drops_unreadable_draft_fail_closed(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    now = time.time()
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO experience_drafts(
                draft_id, status, query_text, title, one_sentence_review,
                time_start, time_end, chapters_json, possible_evidence_json,
                excluded_evidence_json, created_at, updated_at
            ) VALUES (?, 'editing', 'query', 'title', 'review', 1, 2,
                      ?, '[]', '[]', ?, ?)
            """,
            ("draft-corrupt", "not-json", now, now),
        )
        await db.commit()

    deleted = await store.forget_experience_drafts_for_source_events(["event-any"])

    assert deleted == 1
    assert await store.get_experience_draft(draft_id="draft-corrupt") is None


async def _create_draft(
    store,
    *,
    draft_id: str,
    chapters: list[dict[str, object]],
    possible_evidence: list[dict[str, object]] | None = None,
) -> None:
    await store.create_experience_draft(
        draft_id=draft_id,
        query_text=f"query-{draft_id}",
        title=f"title-{draft_id}",
        one_sentence_review=f"review-{draft_id}",
        time_start=100.0,
        time_end=200.0,
        chapters=chapters,
        possible_evidence=possible_evidence or [],
    )
