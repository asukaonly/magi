"""Tests for L3 summary diary essence fields (Plan 1 Task 5)."""

from __future__ import annotations

import pytest

from magi.memory.l3.models import L3Candidate


@pytest.mark.asyncio
async def test_upsert_candidate_persists_narrative_style_and_essence_prose(l3_store_with_schema):
    store = l3_store_with_schema

    candidate = L3Candidate(
        summary_type="temporal",
        summary_category="day",
        content="(legacy summary body)",
        source_event_ids=[],
        insight_key="diary-2026-05-17",  # so we can re-fetch via _find_summary_by_insight_key
    )
    summary = await store.upsert_candidate(
        candidate=candidate,
        summary_overrides={
            "narrative_style": "diary_2p",
            "essence_prose": "周日。你大部分时间在 localhost 之间游走，深夜还亮着屏。",
        },
    )

    assert summary["narrative_style"] == "diary_2p"
    assert summary["essence_prose"] == "周日。你大部分时间在 localhost 之间游走，深夜还亮着屏。"

    # Re-fetch from disk via the row_to_summary_dict path
    fetched = await store._find_summary_by_insight_key(insight_key="diary-2026-05-17")
    assert fetched is not None, "round-trip lookup must succeed"
    assert fetched["narrative_style"] == "diary_2p"
    assert fetched["essence_prose"] == "周日。你大部分时间在 localhost 之间游走，深夜还亮着屏。"


@pytest.mark.asyncio
async def test_default_narrative_style_is_default(l3_store_with_schema):
    store = l3_store_with_schema

    candidate = L3Candidate(
        summary_type="temporal",
        summary_category="day",
        content="legacy",
        source_event_ids=[],
    )
    summary = await store.upsert_candidate(candidate=candidate)

    assert summary["narrative_style"] == "default"
    assert summary.get("essence_prose") is None


@pytest.mark.asyncio
async def test_upsert_existing_summary_preserves_narrative_fields(l3_store_with_schema):
    """Re-upserting an existing insight should keep its narrative_style and essence_prose
    intact unless the new call explicitly overrides them.
    """
    store = l3_store_with_schema

    # First write: set narrative_style and essence_prose
    candidate = L3Candidate(
        summary_type="temporal",
        summary_category="day",
        content="initial body",
        source_event_ids=[],
        insight_key="diary-repeat",
    )
    first = await store.upsert_candidate(
        candidate=candidate,
        summary_overrides={
            "narrative_style": "diary_2p",
            "essence_prose": "first essence",
        },
    )
    assert first["narrative_style"] == "diary_2p"
    assert first["essence_prose"] == "first essence"

    # Second write: same insight_key, different content, NO new override of narrative fields
    second_candidate = L3Candidate(
        summary_type="temporal",
        summary_category="day",
        content="updated body",
        source_event_ids=[],
        insight_key="diary-repeat",
    )
    second = await store.upsert_candidate(candidate=second_candidate)

    # The narrative fields should have been preserved from the first write
    assert second["narrative_style"] == "diary_2p", "existing narrative_style must be preserved"
    assert second["essence_prose"] == "first essence", "existing essence_prose must be preserved"
    # And the content was updated
    assert second["content"] == "updated body"
