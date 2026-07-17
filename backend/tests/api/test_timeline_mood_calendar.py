"""Tests for the mood-calendar service method (Plan 1 Task 12)."""

from __future__ import annotations

import pytest

from magi.timeline.service import TimelineService
from magi.memory.l3.daily_mood.models import DailyMoodAggregate
from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore


@pytest.fixture
def daily_mood_store_for_tests(unified_memory_for_tests):
    """A DailyMoodAggregateStore bound to the same tmp memory.db as the unified-memory fake.

    Writes go through this store, reads through the service that resolves
    its own DailyMoodAggregateStore against unified_memory.memory_db_path —
    both should hit the same file.
    """
    return DailyMoodAggregateStore(db_path=unified_memory_for_tests.memory_db_path)


@pytest.mark.asyncio
async def test_list_mood_calendar_empty_month(unified_memory_for_tests):
    service = TimelineService(unified_memory_for_tests)
    out = await service.list_mood_calendar(month="2026-05")
    assert out == {"month": "2026-05", "days": []}


@pytest.mark.asyncio
async def test_list_mood_calendar_returns_days_in_month(
    unified_memory_for_tests,
    daily_mood_store_for_tests,
):
    await daily_mood_store_for_tests.initialize()

    await daily_mood_store_for_tests.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date="2026-05-10",
            dominant_valence="warm",
            volatility_score=0.2,
            state_curve_compact=[0.4],
            event_count=42,
            source_event_ids=["event-mood-10"],
        )
    )
    await daily_mood_store_for_tests.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date="2026-05-17",
            dominant_valence="cool",
            volatility_score=0.6,
            state_curve_compact=[-0.3, 0.2],
            event_count=228,
            source_event_ids=["event-mood-17"],
        )
    )
    # Out of month — must not appear
    await daily_mood_store_for_tests.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date="2026-04-30",
            dominant_valence="bright",
            volatility_score=0.1,
            state_curve_compact=[0.5],
            event_count=10,
            source_event_ids=["event-mood-april"],
        )
    )

    service = TimelineService(unified_memory_for_tests)
    out = await service.list_mood_calendar(month="2026-05")
    dates = sorted(d["date"] for d in out["days"])
    assert dates == ["2026-05-10", "2026-05-17"]

    day17 = next(d for d in out["days"] if d["date"] == "2026-05-17")
    assert day17["dominant_valence"] == "cool"
    assert day17["volatility"] == pytest.approx(0.6)
    assert day17["event_count"] == 228
    assert day17["sparkline"] == [-0.3, 0.2]


@pytest.mark.asyncio
async def test_list_mood_calendar_rejects_invalid_month(unified_memory_for_tests):
    service = TimelineService(unified_memory_for_tests)
    out = await service.list_mood_calendar(month="not-a-month")
    assert out == {"month": "not-a-month", "days": [], "error": "invalid_month"}
