"""Regression coverage for source-event cleanup of mood projections."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import aiosqlite
import pytest

from magi.memory.l2.store import L2CognitionStore
from magi.memory.l3.daily_mood.models import DailyMoodAggregate
from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore


@pytest.mark.asyncio
async def test_source_forget_removes_only_mood_days_and_is_idempotent(
    l3_store_with_schema,
) -> None:
    db_path = l3_store_with_schema.db_path
    l2 = L2CognitionStore(db_path=db_path)
    await l2.initialize()
    mood_store = DailyMoodAggregateStore(db_path=db_path)
    await mood_store.initialize()
    may_17 = datetime(2026, 5, 17, 12, tzinfo=timezone.utc).timestamp()
    may_18 = datetime(2026, 5, 18, 12, tzinfo=timezone.utc).timestamp()
    await _mood_assertion(l2, event_id="event-mood-17", observed_at=may_17)
    await _mood_assertion(l2, event_id="event-mood-18", observed_at=may_18)
    await _aggregate(mood_store, day="2026-05-17", source_event_id="event-mood-17")
    await _aggregate(mood_store, day="2026-05-18", source_event_id="event-mood-18")
    await _aggregate(mood_store, day="2026-05-19", source_event_id="event-mood-19")

    await l2.forget_source_events(
        ["event-mood-17", "event-mood-18"],
        reason="user_delete_event",
    )
    deleted = await mood_store.forget_source_events(
        [" event-mood-17 ", "event-mood-18", "event-mood-17"],
    )

    assert deleted == 2
    assert await mood_store.get_aggregate(day_local_date="2026-05-17") is None
    assert await mood_store.get_aggregate(day_local_date="2026-05-18") is None
    assert await mood_store.get_aggregate(day_local_date="2026-05-19") is not None
    assert await mood_store.forget_source_events(["event-mood-17", "event-mood-18"]) == 0
    assert await mood_store.forget_source_events([]) == 0


@pytest.mark.asyncio
async def test_orphaned_mood_provenance_clears_projection_fail_closed(
    l3_store_with_schema,
) -> None:
    db_path = l3_store_with_schema.db_path
    mood_store = DailyMoodAggregateStore(db_path=db_path)
    await mood_store.initialize()
    await _aggregate(mood_store, day="2026-05-17", source_event_id="event-other-17")
    await _aggregate(mood_store, day="2026-05-18", source_event_id="event-other-18")
    observed_at = datetime(2026, 5, 17, 12, tzinfo=timezone.utc).timestamp()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_claim_evidence_events(
                target_kind, claim_fingerprint, event_id, observed_at,
                observed_from, observed_to, observed_at_is_approximate,
                created_at
            ) VALUES ('assertion', 'orphaned-claim', 'event-orphaned',
                      ?, ?, ?, 0, ?)
            """,
            (observed_at, observed_at, observed_at, observed_at),
        )
        await db.commit()

    deleted = await mood_store.forget_source_events(["event-orphaned"])

    assert deleted == 2
    assert (
        await mood_store.list_aggregates(
            start_date="2026-01-01",
            end_date="2026-12-31",
        )
        == []
    )


@pytest.mark.asyncio
async def test_concurrent_tombstone_never_leaves_mood_projection_visible(
    l3_store_with_schema,
) -> None:
    db_path = l3_store_with_schema.db_path
    mood_store = DailyMoodAggregateStore(db_path=db_path)
    await mood_store.initialize()
    aggregate = DailyMoodAggregate(
        day_local_date="2026-05-17",
        dominant_valence="warm",
        volatility_score=0.2,
        state_curve_compact=[0.5],
        event_count=1,
        source_event_ids=["event-race"],
    )

    async def tombstone() -> None:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
                VALUES ('event-race', 'user_delete_event', ?)
                """,
                (time.time(),),
            )
            await db.commit()

    await asyncio.gather(mood_store.upsert_aggregate(aggregate), tombstone())

    assert await mood_store.get_aggregate(day_local_date="2026-05-17") is None


@pytest.mark.asyncio
async def test_time_range_block_hides_and_rejects_mood_without_blocking_episode_sources(
    l3_store_with_schema,
) -> None:
    db_path = l3_store_with_schema.db_path
    mood_store = DailyMoodAggregateStore(db_path=db_path)
    await mood_store.initialize()
    await _aggregate(mood_store, day="2026-05-17", source_event_id="event-time-range")
    await _aggregate(mood_store, day="2026-05-18", source_event_id="event-episode-only")
    async with aiosqlite.connect(db_path) as db:
        await db.executemany(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (?, ?, ?, '{}', 'test', 1, 1)
            """,
            [
                ("operation-time-mood", "time_range", "hash-time-mood"),
                ("operation-episode-mood", "episode", "hash-episode-mood"),
            ],
        )
        await db.executemany(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES ('episode_formation', ?, ?, ?, 1)
            """,
            [
                ("time:hash-time-mood", "event-time-range", "operation-time-mood"),
                ("episode:ordinary", "event-episode-only", "operation-episode-mood"),
            ],
        )
        await db.commit()

    assert await mood_store.get_aggregate(day_local_date="2026-05-17") is None
    assert await mood_store.get_aggregate(day_local_date="2026-05-18") is not None
    assert not await mood_store.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date="2026-05-19",
            dominant_valence="warm",
            volatility_score=0.2,
            state_curve_compact=[0.5],
            event_count=1,
            source_event_ids=["event-time-range"],
        )
    )
    assert await mood_store.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date="2026-05-20",
            dominant_valence="warm",
            volatility_score=0.2,
            state_curve_compact=[0.5],
            event_count=1,
            source_event_ids=["event-episode-only"],
        )
    )


async def _mood_assertion(
    store: L2CognitionStore,
    *,
    event_id: str,
    observed_at: float,
) -> str:
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:default",
            "entity_type": "user",
            "trait_family": "mood",
            "trait_name": "valence",
            "trait_value": "0.5",
            "confidence_score": 0.8,
            "evidence_events": [event_id],
            "volatility_index": 0.8,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "tentative",
            "first_inferred_at": observed_at,
            "last_validated_at": observed_at,
            "temporal_scope": "recent",
        }
    )


async def _aggregate(
    store: DailyMoodAggregateStore,
    *,
    day: str,
    source_event_id: str,
) -> None:
    await store.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date=day,
            dominant_valence="warm",
            volatility_score=0.2,
            state_curve_compact=[0.5],
            event_count=1,
            source_event_ids=[source_event_id],
        )
    )
