"""Tests for L3SummaryStore FTS5 integration."""

from __future__ import annotations

import time
import uuid

import pytest

from magi.memory.l3.summary_store import L3SummaryStore
from magi.memory.l3.daily_mood.models import DailyMoodAggregate
from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore


def _make_summary(content: str, **overrides) -> dict:
    """Create a minimal summary dict for testing."""
    now = time.time()
    base = {
        "summary_id": f"summary_{uuid.uuid4().hex}",
        "summary_type": "temporal",
        "summary_category": "daily",
        "period_start": now - 86400,
        "period_end": now,
        "content": content,
        "key_topics": [],
        "key_entities": [],
        "sentiment_summary": None,
        "source_event_ids": ["evt-1"],
        "source_event_count": 1,
        "importance_aggregate": 0.5,
        "event_type_distribution": {},
        "generated_by_model": "rule-summary",
        "generation_prompt": None,
        "generation_reason": "temporal:daily",
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return base


@pytest.fixture
async def store(tmp_path):
    s = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await s.initialize()
    yield s


class TestL3FTS5TableCreation:
    @pytest.mark.asyncio
    async def test_fts5_table_exists(self, store):
        import aiosqlite

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='l3_summaries_fts'"
            ) as cursor:
                row = await cursor.fetchone()
        assert row is not None, "FTS5 virtual table l3_summaries_fts should exist"


class TestL3FTS5WriteSync:
    @pytest.mark.asyncio
    async def test_store_summary_populates_fts(self, store):
        import aiosqlite

        summary = _make_summary("User discussed project deadlines")
        await store._store_summary(summary)

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT summary_id FROM l3_summaries_fts WHERE l3_summaries_fts MATCH ?",
                ("project",),
            ) as cursor:
                rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == summary["summary_id"]

    @pytest.mark.asyncio
    async def test_store_summary_indexes_structured_fields(self, store):
        summary = _make_summary(
            "General weekly recap",
            key_topics=["planning"],
            change_and_pattern={
                "source_signals": ["Chrome searches focused on PoE switch procurement"],
                "open_threads": ["Gemini remained an active planning assistant"],
            },
        )
        await store._store_summary(summary)

        bm25_results = await store.bm25_search("Gemini")
        keyword_results = await store.keyword_search(query="PoE switch", limit=10)

        assert [result[0] for result in bm25_results] == [summary["summary_id"]]
        assert keyword_results == [summary["summary_id"]]

    @pytest.mark.asyncio
    async def test_upsert_updates_fts(self, store):
        import aiosqlite

        summary = _make_summary("Original content about cats")
        await store._store_summary(summary)

        summary["content"] = "Updated content about dogs"
        summary["updated_at"] = time.time()
        await store._store_summary(summary)

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM l3_summaries_fts WHERE summary_id = ?",
                (summary["summary_id"],),
            ) as cursor:
                count = (await cursor.fetchone())[0]
        assert count == 1

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT summary_id FROM l3_summaries_fts WHERE l3_summaries_fts MATCH ?",
                ("dogs",),
            ) as cursor:
                rows = await cursor.fetchall()
        assert len(rows) == 1


class TestL3FTS5DeleteSync:
    @pytest.mark.asyncio
    async def test_clear_removes_fts_entries(self, store):
        import aiosqlite

        for i in range(3):
            await store._store_summary(_make_summary(f"Summary number {i}"))

        await store.clear()

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l3_summaries_fts") as cursor:
                count = (await cursor.fetchone())[0]
        assert count == 0

    @pytest.mark.asyncio
    async def test_clear_removes_daily_mood_aggregates(self, store):
        mood_store = DailyMoodAggregateStore(store.db_path)
        await mood_store.upsert_aggregate(
            DailyMoodAggregate(
                day_local_date="2026-07-15",
                dominant_valence="positive",
                volatility_score=0.2,
                state_curve_compact=[0.2, 0.6],
                event_count=3,
                source_event_ids=["event-mood-one", "event-mood-two"],
                computed_at=time.time(),
            )
        )

        await store.clear()

        assert await mood_store.get_aggregate(day_local_date="2026-07-15") is None


class TestL3BM25Search:
    @pytest.mark.asyncio
    async def test_basic_bm25_search(self, store):
        await store._store_summary(
            _make_summary("Machine learning and neural networks are powerful")
        )
        await store._store_summary(_make_summary("Grocery shopping list includes milk and eggs"))
        await store._store_summary(_make_summary("Deep learning is a subset of machine learning"))

        results = await store.bm25_search("machine learning")
        assert len(results) >= 1
        ids = [r[0] for r in results]
        # Both ML summaries should be found
        assert len(ids) >= 2

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        await store._store_summary(_make_summary("Some content"))
        results = await store.bm25_search("")
        assert results == []

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, store):
        await store._store_summary(_make_summary("Cats and dogs"))
        results = await store.bm25_search("quantum physics")
        assert results == []

    @pytest.mark.asyncio
    async def test_limit_respected(self, store):
        for i in range(10):
            await store._store_summary(_make_summary(f"Test summary about topic alpha {i}"))

        results = await store.bm25_search("alpha", limit=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_chinese_search(self, store):
        await store._store_summary(_make_summary("用户今天讨论了机器学习和深度学习的区别"))
        await store._store_summary(_make_summary("天气晴朗适合户外活动"))

        results = await store.bm25_search("机器学习")
        assert len(results) >= 1


class TestL3BackfillFTS:
    @pytest.mark.asyncio
    async def test_backfill_indexes_existing_summaries(self, store):
        import aiosqlite

        # Insert directly into summaries table bypassing FTS sync
        summary = _make_summary("Directly inserted summary about quantum computing")
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute(
                """INSERT INTO summaries(
                    summary_id, summary_type, summary_category, period_start, period_end,
                    content, key_topics, key_entities, sentiment_summary, source_event_ids,
                    source_event_count, importance_aggregate, event_type_distribution,
                    generated_by_model, generation_prompt, generation_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    summary["summary_id"],
                    summary["summary_type"],
                    summary["summary_category"],
                    summary["period_start"],
                    summary["period_end"],
                    summary["content"],
                    "[]",
                    "[]",
                    None,
                    '["evt-1"]',
                    1,
                    0.5,
                    "{}",
                    "rule-summary",
                    None,
                    "temporal:daily",
                    summary["created_at"],
                    summary["updated_at"],
                ),
            )
            await db.commit()

        # FTS should NOT find it yet
        results = await store.bm25_search("quantum")
        assert results == []

        # Backfill
        indexed = await store.backfill_fts()
        assert indexed == 1

        # Now FTS should find it
        results = await store.bm25_search("quantum")
        assert len(results) == 1
        assert results[0][0] == summary["summary_id"]

    @pytest.mark.asyncio
    async def test_backfill_skips_already_indexed(self, store):
        await store._store_summary(_make_summary("Already indexed content"))

        indexed = await store.backfill_fts()
        assert indexed == 0
