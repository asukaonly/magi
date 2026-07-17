"""Tests for the daily_mood_aggregate store."""

from __future__ import annotations

import aiosqlite
import pytest

from _shared.memory_schema import apply_memory_shared_schema


@pytest.mark.asyncio
async def test_upsert_and_get_aggregate(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = DailyMoodAggregateStore(db_path=db_path)
    await store.initialize()

    agg = DailyMoodAggregate(
        day_local_date="2026-05-17",
        dominant_valence="cool",
        volatility_score=0.62,
        state_curve_compact=[0.1, 0.1, -0.3, -0.3, 0.0, 0.4, 0.4, 0.2],
        event_count=228,
        source_event_ids=["event-aggregate"],
    )
    await store.upsert_aggregate(agg)

    got = await store.get_aggregate(day_local_date="2026-05-17")
    assert got is not None
    assert got.day_local_date == "2026-05-17"
    assert got.dominant_valence == "cool"
    assert got.volatility_score == pytest.approx(0.62)
    assert got.event_count == 228
    assert got.source_event_ids == ["event-aggregate"]
    assert got.state_curve_compact[0] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_upsert_overwrites_same_day(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = DailyMoodAggregateStore(db_path=db_path)
    await store.initialize()

    await store.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date="2026-05-17",
            dominant_valence="neutral",
            volatility_score=0.0,
            state_curve_compact=[],
            event_count=10,
            source_event_ids=["event-old"],
        )
    )
    await store.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date="2026-05-17",
            dominant_valence="warm",
            volatility_score=0.3,
            state_curve_compact=[0.5],
            event_count=20,
            source_event_ids=["event-new"],
        )
    )
    got = await store.get_aggregate(day_local_date="2026-05-17")
    assert got.dominant_valence == "warm"
    assert got.event_count == 20


@pytest.mark.asyncio
async def test_list_aggregates_in_range(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = DailyMoodAggregateStore(db_path=db_path)
    await store.initialize()

    for d in ("2026-05-10", "2026-05-12", "2026-05-15", "2026-05-20"):
        await store.upsert_aggregate(
            DailyMoodAggregate(
                day_local_date=d,
                dominant_valence="neutral",
                volatility_score=0.0,
                state_curve_compact=[],
                event_count=1,
                source_event_ids=[f"event-{d}"],
            )
        )

    rows = await store.list_aggregates(start_date="2026-05-11", end_date="2026-05-17")
    dates = sorted(r.day_local_date for r in rows)
    assert dates == ["2026-05-12", "2026-05-15"]


@pytest.mark.asyncio
async def test_non_empty_aggregate_requires_source_lineage(tmp_path):
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = DailyMoodAggregateStore(db_path=db_path)

    with pytest.raises(ValueError, match="require source_event_ids"):
        await store.upsert_aggregate(
            DailyMoodAggregate(
                day_local_date="2026-05-17",
                dominant_valence="warm",
                event_count=1,
            )
        )


@pytest.mark.asyncio
async def test_unattributable_stored_aggregate_is_hidden(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = DailyMoodAggregateStore(db_path=db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            INSERT INTO daily_mood_aggregate(
                day_local_date, dominant_valence, volatility_score,
                state_curve_compact, event_count, source_event_ids, computed_at
            ) VALUES ('2026-05-17', 'warm', 0.2, '[0.5]', 1, '[]', 1)
            """)
        await db.commit()

    assert await store.get_aggregate(day_local_date="2026-05-17") is None
