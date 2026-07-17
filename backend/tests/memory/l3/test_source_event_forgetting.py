from __future__ import annotations

import json

import aiosqlite
import pytest

from magi.memory.l3.models import L3Candidate
from magi.memory.l3.storage.operations import ForgottenSummarySourceEventError
from magi.memory.source_event_governance import tombstone_source_event_ids


async def _store_summary(store, *, key: str, event_ids: list[str]):  # type: ignore[no-untyped-def]
    return await store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="thematic",
            summary_category="topic",
            content=f"Generated private content for {key}",
            source_event_ids=event_ids,
            insight_key=key,
        )
    )


@pytest.mark.asyncio
async def test_forget_source_events_hides_direct_l3_derivations(
    l3_store_with_schema,
) -> None:
    store = l3_store_with_schema
    mixed = await _store_summary(
        store,
        key="mixed-source-summary",
        event_ids=["evt-remove", "evt-keep"],
    )
    sole = await _store_summary(
        store,
        key="sole-source-summary",
        event_ids=["evt-remove"],
    )

    assert await store.forget_source_events(["evt-remove"]) == 2

    assert await store.get_summary_by_id(mixed["summary_id"]) is None
    assert await store.get_summary_by_id(sole["summary_id"]) is None
    mixed_links = await store.list_summary_event_links(mixed["summary_id"])
    assert [link["event_id"] for link in mixed_links] == ["evt-keep"]
    assert await store.list_summary_event_links(sole["summary_id"]) == []

    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            """
            SELECT summary_id, source_event_ids, source_event_count,
                   derivation_state, content
            FROM summaries
            WHERE summary_id IN (?, ?)
            ORDER BY summary_id
            """,
            (mixed["summary_id"], sole["summary_id"]),
        ) as cursor:
            rows = await cursor.fetchall()
        async with db.execute(
            """
            SELECT COUNT(*) FROM l3_summaries_fts
            WHERE summary_id IN (?, ?)
            """,
            (mixed["summary_id"], sole["summary_id"]),
        ) as cursor:
            fts_count = await cursor.fetchone()

    by_id = {str(row[0]): row for row in rows}
    assert json.loads(by_id[mixed["summary_id"]][1]) == ["evt-keep"]
    assert by_id[mixed["summary_id"]][2:4] == (1, "stale")
    assert json.loads(by_id[sole["summary_id"]][1]) == []
    assert by_id[sole["summary_id"]][2:4] == (0, "retired")
    assert "Generated private content" in str(by_id[mixed["summary_id"]][4])
    assert fts_count == (0,)


@pytest.mark.asyncio
async def test_summary_persistence_rejects_tombstoned_sources_and_stale_revival(
    l3_store_with_schema,
) -> None:
    store = l3_store_with_schema
    existing = await _store_summary(
        store,
        key="guarded-existing-summary",
        event_ids=["evt-forgotten", "evt-safe"],
    )
    await store.forget_source_events(["evt-forgotten"])
    async with aiosqlite.connect(store.db_path) as db:
        await tombstone_source_event_ids(
            db,
            event_ids=["evt-forgotten"],
            reason="user_delete_event",
            created_at=100.0,
        )
        await db.commit()

    with pytest.raises(ForgottenSummarySourceEventError):
        await _store_summary(
            store,
            key="guarded-new-summary",
            event_ids=["evt-forgotten"],
        )
    with pytest.raises(ForgottenSummarySourceEventError):
        await _store_summary(
            store,
            key="guarded-existing-summary",
            event_ids=["evt-forgotten", "evt-safe-2"],
        )

    assert await store.get_summary_by_id(existing["summary_id"]) is None
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM summaries WHERE insight_key = 'guarded-new-summary'"
        ) as cursor:
            assert await cursor.fetchone() == (0,)
        async with db.execute(
            """
            SELECT derivation_state, source_event_ids
            FROM summaries WHERE summary_id = ?
            """,
            (existing["summary_id"],),
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "stale"
    assert json.loads(row[1]) == ["evt-safe"]


@pytest.mark.asyncio
async def test_time_range_block_hides_and_rejects_l3_without_blocking_episode_sources(
    l3_store_with_schema,
) -> None:
    store = l3_store_with_schema
    time_summary = await _store_summary(
        store,
        key="time-range-source",
        event_ids=["evt-time-range"],
    )
    episode_summary = await _store_summary(
        store,
        key="ordinary-episode-source",
        event_ids=["evt-episode-only"],
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.executemany(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (?, ?, ?, '{}', 'test', 1, 1)
            """,
            [
                ("operation-time-l3", "time_range", "hash-time-l3"),
                ("operation-episode-l3", "episode", "hash-episode-l3"),
            ],
        )
        await db.executemany(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES ('episode_formation', ?, ?, ?, 1)
            """,
            [
                ("time:hash-time-l3", "evt-time-range", "operation-time-l3"),
                ("episode:ordinary", "evt-episode-only", "operation-episode-l3"),
            ],
        )
        await db.commit()

    assert await store.get_summary_by_id(time_summary["summary_id"]) is None
    assert await store.get_summary_by_id(episode_summary["summary_id"]) is not None
    with pytest.raises(ForgottenSummarySourceEventError):
        await _store_summary(
            store,
            key="late-time-range-source",
            event_ids=["evt-time-range"],
        )
    replacement = await _store_summary(
        store,
        key="time-range-source",
        event_ids=["evt-after-time-range"],
    )
    assert replacement["summary_id"] == time_summary["summary_id"]
    assert replacement["source_event_ids"] == ["evt-after-time-range"]
    assert await store.get_summary_by_id(time_summary["summary_id"]) is not None
    assert (
        await _store_summary(
            store,
            key="late-ordinary-episode-source",
            event_ids=["evt-episode-only"],
        )
    )["summary_id"]
