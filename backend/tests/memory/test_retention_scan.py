"""Bounded retention passes keep progress while preserving live evidence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import aiosqlite
import pytest
import pytest_asyncio

from magi.memory.event_contracts import RetentionClass
from magi.memory.l3.models import L3Candidate
from magi.memory.retention_scan import (
    advance_retention_scan_cursor,
    load_retention_scan_cursor,
)
from magi.memory.shared_clear import clear_shared_auxiliary_memory
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore


def _memory(root: Path) -> UnifiedMemoryStore:
    return UnifiedMemoryStore(
        persist_dir=str(root / "memory"),
        l1_db_path=str(root / "l1.db"),
        memory_db_path=str(root / "memory.db"),
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )


@pytest_asyncio.fixture
async def memory(tmp_path):
    store = _memory(tmp_path)
    await store.initialize()
    yield store
    await store.shutdown()


async def _seed_events(memory: UnifiedMemoryStore, count: int) -> list[str]:
    event_ids = [f"event-{index:05d}" for index in range(count)]
    async with aiosqlite.connect(memory.l1.db_path) as db:
        await db.executemany(
            """
            INSERT INTO fact_events (
                event_id, timestamp, created_at, event_type, source, memory_domain,
                retention_class, content, author_type, content_type
            ) VALUES (?, 1, 1, 'UserMessage', 'chat', 1, ?, 'Synthetic evidence', 1, 1)
            """,
            [(event_id, int(RetentionClass.COMPRESSIBLE)) for event_id in event_ids],
        )
        await db.commit()
    return event_ids


async def _cover_events(memory: UnifiedMemoryStore, event_ids: list[str]) -> str:
    summary = await memory.l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="insight",
            summary_category="state_change",
            content="Synthetic summary covering retained evidence.",
            source_event_ids=event_ids,
        ),
        summary_overrides={"period_start": 1.0, "period_end": 1.0},
    )
    return str(summary["summary_id"])


@pytest.mark.asyncio
async def test_l1_scan_reaches_covered_tail_after_default_page_of_uncovered_events(memory):
    event_ids = await _seed_events(memory, 10_001)
    await _cover_events(memory, [event_ids[-1]])

    first = await memory.cleanup_l1_data(older_than_days=30)
    scan = await load_retention_scan_cursor(memory.memory_db_path, "l1")
    assert first["deleted_events"] == 0
    assert scan.position == (1.0, event_ids[9_999])

    second = await memory.cleanup_l1_data(older_than_days=30)
    assert second["deleted_events"] == 1
    assert await memory.l1.get_active_event(event_ids[-1]) is None
    assert await memory.l1.get_active_event(event_ids[0]) is not None
    assert (await load_retention_scan_cursor(memory.memory_db_path, "l1")).position is None


@pytest.mark.asyncio
async def test_l1_scan_restarts_from_persisted_keyset_and_revisits_released_evidence(
    memory, tmp_path, monkeypatch,
):
    monkeypatch.setattr("magi.memory.store_maintenance.RETENTION_SCAN_LIMIT", 2)
    event_ids = await _seed_events(memory, 4)
    await _cover_events(memory, event_ids[1:3])
    await memory.l2.create_episode(
        episode_id="protected", status="active", time_start=1.0, time_end=2.0,
        label="Protected evidence", source_event_count=1,
    )
    await memory.l2.add_episode_events(episode_id="protected", event_ids=[event_ids[1]])
    assert (await memory.cleanup_l1_data())["deleted_events"] == 0
    first_scan = await load_retention_scan_cursor(memory.memory_db_path, "l1")
    assert first_scan.position == (1.0, event_ids[1])

    reopened = _memory(tmp_path)
    await reopened.initialize()
    try:
        assert (await reopened.cleanup_l1_data())["deleted_events"] == 1
        second_scan = await load_retention_scan_cursor(reopened.memory_db_path, "l1")
        assert second_scan.position == (1.0, event_ids[3])
        assert second_scan.cutoff_at == first_scan.cutoff_at
        assert await reopened.l1.get_active_event(event_ids[1]) is not None
        async with aiosqlite.connect(reopened.memory_db_path) as db:
            await db.execute("UPDATE episodes SET status = 'archived' WHERE episode_id = 'protected'")
            await db.commit()
        # An exactly full last page wraps on its following empty pass.
        assert (await reopened.cleanup_l1_data())["deleted_events"] == 0
        assert (await load_retention_scan_cursor(reopened.memory_db_path, "l1")).position is None
        assert (await reopened.cleanup_l1_data())["deleted_events"] == 1
        assert await reopened.l1.get_active_event(event_ids[1]) is None
        assert await reopened.l1.get_active_event(event_ids[0]) is not None
    finally:
        await reopened.shutdown()


@pytest.mark.asyncio
async def test_l3_scan_keeps_confirmed_rows_but_reaches_unprotected_tail(memory, monkeypatch):
    monkeypatch.setattr("magi.memory.store_maintenance.RETENTION_SCAN_LIMIT", 2)
    async with aiosqlite.connect(memory.memory_db_path) as db:
        await db.executemany(
            """
            INSERT INTO summaries (
                summary_id, summary_type, summary_category, period_start, period_end,
                content, source_event_ids, source_event_count, created_at, updated_at,
                derivation_state, review_state, insight_metadata
            ) VALUES (?, 'temporal', 'day', 1, 1, 'Synthetic summary', '[]', 0,
                      1, 1, 'current', ?, '{}')
            """,
            [("summary-a", "confirmed"), ("summary-b", "confirmed"), ("summary-c", "neutral")],
        )
        await db.commit()

    assert (await memory.cleanup_l3_data())["deleted_summaries"] == 0
    scan = await load_retention_scan_cursor(memory.memory_db_path, "l3")
    assert scan.position == (1.0, "summary-b")
    assert (await memory.cleanup_l3_data())["deleted_summaries"] == 1
    assert await memory.l3.get_summary_by_id("summary-c") is None
    assert await memory.l3.get_summary_by_id("summary-a") is not None
    assert (await load_retention_scan_cursor(memory.memory_db_path, "l3")).position is None

    async with aiosqlite.connect(memory.memory_db_path) as db:
        await db.execute("UPDATE summaries SET review_state = 'neutral'")
        await db.commit()
    assert (await memory.cleanup_l3_data())["deleted_summaries"] == 2


@pytest.mark.asyncio
async def test_failed_page_does_not_checkpoint_past_unfinished_deletions(memory, monkeypatch):
    event_ids = await _seed_events(memory, 1)
    await _cover_events(memory, event_ids)
    original_delete = memory.l1.mark_deleted
    monkeypatch.setattr(memory.l1, "mark_deleted", AsyncMock(side_effect=OSError("write failed")))
    with pytest.raises(OSError, match="write failed"):
        await memory.cleanup_l1_data()
    assert (await load_retention_scan_cursor(memory.memory_db_path, "l1")).revision == 0
    monkeypatch.setattr(memory.l1, "mark_deleted", original_delete)
    assert (await memory.cleanup_l1_data())["deleted_events"] == 1


@pytest.mark.asyncio
async def test_cursor_revision_prevents_regression_and_clear_retires_progress(memory):
    original = await load_retention_scan_cursor(memory.memory_db_path, "l1")
    assert await advance_retention_scan_cursor(
        memory.memory_db_path, layer="l1", previous=original,
        cutoff_at=100, positions=[(1, "event-a")], limit=1,
    )
    newer = await load_retention_scan_cursor(memory.memory_db_path, "l1")
    assert await advance_retention_scan_cursor(
        memory.memory_db_path, layer="l1", previous=newer,
        cutoff_at=100, positions=[(2, "event-b")], limit=1,
    )
    assert not await advance_retention_scan_cursor(
        memory.memory_db_path, layer="l1", previous=original,
        cutoff_at=100, positions=[(1, "event-a")], limit=1,
    )
    assert (await load_retention_scan_cursor(memory.memory_db_path, "l1")).position == (2, "event-b")
    await clear_shared_auxiliary_memory(memory.memory_db_path)
    assert (await load_retention_scan_cursor(memory.memory_db_path, "l1")).position is None
    assert not await advance_retention_scan_cursor(
        memory.memory_db_path, layer="l1", previous=newer,
        cutoff_at=100, positions=[(2, "event-b")], limit=1,
    )
