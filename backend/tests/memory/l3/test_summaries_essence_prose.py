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

    # And re-fetched from disk
    fetched = await store._find_summary_by_insight_key(insight_key=summary.get("insight_key") or "")
    # If insight_key is None the above returns None; query through the SELECT path instead.
    if fetched is None:
        import aiosqlite
        from magi.core.sqlite import sqlite_connection_async

        async with sqlite_connection_async(store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT narrative_style, essence_prose FROM summaries WHERE summary_id = ?",
                (summary["summary_id"],),
            ) as cursor:
                row = await cursor.fetchone()
            assert row is not None
            assert row["narrative_style"] == "diary_2p"
            assert row["essence_prose"] == "周日。你大部分时间在 localhost 之间游走，深夜还亮着屏。"
    else:
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
    assert summary.get("essence_prose") in (None, "")
