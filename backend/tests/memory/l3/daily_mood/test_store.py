"""Tests for the daily_mood_aggregate store."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_upsert_and_get_aggregate(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    store = DailyMoodAggregateStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()

    agg = DailyMoodAggregate(
        day_local_date="2026-05-17",
        dominant_valence="cool",
        volatility_score=0.62,
        state_curve_compact=[0.1, 0.1, -0.3, -0.3, 0.0, 0.4, 0.4, 0.2],
        event_count=228,
    )
    await store.upsert_aggregate(agg)

    got = await store.get_aggregate(day_local_date="2026-05-17")
    assert got is not None
    assert got.day_local_date == "2026-05-17"
    assert got.dominant_valence == "cool"
    assert got.volatility_score == pytest.approx(0.62)
    assert got.event_count == 228
    assert got.state_curve_compact[0] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_upsert_overwrites_same_day(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    store = DailyMoodAggregateStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()

    await store.upsert_aggregate(DailyMoodAggregate(
        day_local_date="2026-05-17", dominant_valence="neutral",
        volatility_score=0.0, state_curve_compact=[], event_count=10,
    ))
    await store.upsert_aggregate(DailyMoodAggregate(
        day_local_date="2026-05-17", dominant_valence="warm",
        volatility_score=0.3, state_curve_compact=[0.5], event_count=20,
    ))
    got = await store.get_aggregate(day_local_date="2026-05-17")
    assert got.dominant_valence == "warm"
    assert got.event_count == 20


@pytest.mark.asyncio
async def test_list_aggregates_in_range(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    store = DailyMoodAggregateStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()

    for d in ("2026-05-10", "2026-05-12", "2026-05-15", "2026-05-20"):
        await store.upsert_aggregate(DailyMoodAggregate(
            day_local_date=d, dominant_valence="neutral",
            volatility_score=0.0, state_curve_compact=[], event_count=1,
        ))

    rows = await store.list_aggregates(start_date="2026-05-11", end_date="2026-05-17")
    dates = sorted(r.day_local_date for r in rows)
    assert dates == ["2026-05-12", "2026-05-15"]
