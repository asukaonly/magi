"""Tests for L3 summary diary essence fields (Plan 1 Task 5)."""

from __future__ import annotations

import pytest

from magi.memory.l3.models import L3Candidate


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides, style, prose",
    [
        ({}, "default", None),
        (
            {"narrative_style": "diary_2p", "essence_prose": "saved diary prose"},
            "diary_2p",
            "saved diary prose",
        ),
    ],
)
async def test_narrative_fields_survive_persistence(l3_store_with_schema, overrides, style, prose):
    store = l3_store_with_schema
    candidate = L3Candidate(
        summary_type="temporal",
        summary_category="day",
        content="summary",
        source_event_ids=[],
        insight_key="diary-fields",
    )
    summary = await store.upsert_candidate(candidate=candidate, summary_overrides=overrides)
    fetched = await store._find_summary_by_insight_key(insight_key="diary-fields")
    assert fetched["summary_id"] == summary["summary_id"]
    assert fetched["narrative_style"] == style
    assert fetched["essence_prose"] == prose


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
