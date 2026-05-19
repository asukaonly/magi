"""Tests that the viewport response surfaces Plan-1/2 immersive fields."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from magi.memory.l2.store import L2CognitionStore
from magi.memory.l3.summary_store import L3SummaryStore
from magi.memory.l3.models import L3Candidate
from magi.timeline.service import TimelineService


@pytest.mark.asyncio
async def test_viewport_cluster_surfaces_slice_narrative_and_asset_ref(
    unified_memory_for_tests, l2_store_for_tests: L2CognitionStore,
):
    # Seed an active episode with all the new immersive fields populated
    await l2_store_for_tests.create_episode(
        episode_id="ep-imm", time_start=100.0, time_end=200.0,
        slice_narrative="下午你读了 timeline-domain 的架构文档。",
        slice_sensory_detail="窗外光线很柔。",
        representative_asset_ref="photo-library://2026-05-17/IMG.HEIC",
    )
    await l2_store_for_tests.update_episode(
        episode_id="ep-imm", status="active", label="afternoon coding",
    )

    service = TimelineService(unified_memory_for_tests)
    viewport = await service.get_viewport(
        scale="day", start=0.0, end=500.0,
        query=None, timezone=None, locale="zh", focus="self",
    )

    clusters = viewport.get("clusters") or []
    assert clusters, "expected at least one cluster from the active episode"
    cluster = next((c for c in clusters if c.get("episode_id") == "ep-imm"), None)
    assert cluster is not None, f"ep-imm not in clusters: {[c.get('episode_id') for c in clusters]}"
    assert cluster.get("slice_narrative") == "下午你读了 timeline-domain 的架构文档。"
    assert cluster.get("slice_sensory_detail") == "窗外光线很柔。"
    assert cluster.get("representative_asset_ref") == "photo-library://2026-05-17/IMG.HEIC"


@pytest.mark.asyncio
async def test_viewport_overview_surfaces_essence_prose_when_l3_exists(
    unified_memory_for_tests, l2_store_for_tests,
):
    # Seed an L3 diary summary for 2024-05-20 UTC
    l3_store = L3SummaryStore(db_path=str(unified_memory_for_tests.memory_db_path))
    await l3_store.initialize()
    await l3_store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="temporal",
            summary_category="day",
            content="essence body",
            source_event_ids=[],
            insight_key="diary-day-2024-05-20",
        ),
        summary_overrides={
            "narrative_style": "diary_2p",
            "essence_prose": "周日。你大部分时间在 localhost 之间游走。",
        },
    )

    # Attach the L3 store to the unified_memory fixture so the service can find it
    unified_memory_for_tests.l3 = l3_store

    # Day window: 2024-05-20 00:00 UTC – 2024-05-21 00:00 UTC
    day_start = datetime(2024, 5, 20, tzinfo=timezone.utc).timestamp()
    day_end = day_start + 86400.0

    service = TimelineService(unified_memory_for_tests)
    viewport = await service.get_viewport(
        scale="day", start=day_start, end=day_end,
        query=None, timezone=None, locale="zh", focus="self",
    )

    overview = viewport.get("overview") or {}
    assert overview.get("essence_prose") == "周日。你大部分时间在 localhost 之间游走。"


@pytest.mark.asyncio
async def test_viewport_overview_essence_prose_empty_when_no_l3(
    unified_memory_for_tests,
):
    """When no L3 diary summary exists for the window, essence_prose is empty string."""
    service = TimelineService(unified_memory_for_tests)
    # Year 2099 → guaranteed no L3 data
    far_future_start = datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp()
    viewport = await service.get_viewport(
        scale="day", start=far_future_start, end=far_future_start + 86400.0,
        query=None, timezone=None, locale="zh", focus="self",
    )
    assert viewport.get("overview", {}).get("essence_prose") == ""
