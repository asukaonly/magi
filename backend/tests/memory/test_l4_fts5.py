"""Tests for L4ProceduralMemoryStore FTS5 integration."""
from __future__ import annotations

import time

import pytest

from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)


def _make_action_event(
    action_type: str = "test.action",
    success: bool = True,
    execution_time: float = 0.1,
) -> MemoryEvent:
    import json

    now = time.time()
    return MemoryEvent(
        event_id=f"evt-{time.time_ns()}",
        correlation_id=f"corr-{time.time_ns()}",
        event_type="ActionExecuted",
        timestamp=now,
        created_at=now,
        source="worker",
        source_item_id=action_type,
        memory_domain=MemoryDomain.USER_AUTHORED,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id=None,
        task_id=None,
        content=json.dumps({
            "action_type": action_type,
            "success": success,
            "execution_time": execution_time,
        }, ensure_ascii=False),
        author_type="tool",
        content_type="tool_result",
        importance_score=0.5,
        level=20,
    )


@pytest.fixture
async def store(tmp_path):
    s = L4ProceduralMemoryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await s.initialize()
    yield s


class TestL4FTS5TableCreation:
    @pytest.mark.asyncio
    async def test_fts5_table_exists(self, store):
        import aiosqlite

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='l4_skills_fts'"
            ) as cursor:
                row = await cursor.fetchone()
        assert row is not None, "FTS5 virtual table l4_skills_fts should exist"


class TestL4FTS5WriteSync:
    @pytest.mark.asyncio
    async def test_new_skill_populates_fts(self, store):
        import aiosqlite

        event = _make_action_event(action_type="web_search.google")
        skill_id = await store.record_memory_event(event)
        assert skill_id is not None

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT skill_id FROM l4_skills_fts WHERE l4_skills_fts MATCH ?",
                ("web_search",),
            ) as cursor:
                rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == skill_id

    @pytest.mark.asyncio
    async def test_update_skill_updates_fts(self, store):
        import aiosqlite

        event1 = _make_action_event(action_type="file.read")
        skill_id = await store.record_memory_event(event1)

        event2 = _make_action_event(action_type="file.read", success=False)
        skill_id2 = await store.record_memory_event(event2)
        assert skill_id2 == skill_id

        # FTS should have exactly 1 entry for this skill
        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM l4_skills_fts WHERE skill_id = ?",
                (skill_id,),
            ) as cursor:
                count = (await cursor.fetchone())[0]
        assert count == 1


class TestL4FTS5DeleteSync:
    @pytest.mark.asyncio
    async def test_clear_removes_fts_entries(self, store):
        import aiosqlite

        await store.record_memory_event(_make_action_event(action_type="bash.execute"))
        await store.record_memory_event(_make_action_event(action_type="web_fetch.url"))

        await store.clear()

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l4_skills_fts") as cursor:
                count = (await cursor.fetchone())[0]
        assert count == 0


class TestL4BM25Search:
    @pytest.mark.asyncio
    async def test_basic_bm25_search(self, store):
        await store.record_memory_event(_make_action_event(action_type="browser.open"))
        await store.record_memory_event(_make_action_event(action_type="file.write"))
        await store.record_memory_event(_make_action_event(action_type="browser.navigate"))

        results = await store.bm25_search("browser")
        assert len(results) >= 1
        ids = [r[0] for r in results]
        assert len(ids) >= 2

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        await store.record_memory_event(_make_action_event())
        results = await store.bm25_search("")
        assert results == []

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, store):
        await store.record_memory_event(_make_action_event(action_type="file.read"))
        results = await store.bm25_search("quantum physics")
        assert results == []

    @pytest.mark.asyncio
    async def test_limit_respected(self, store):
        for i in range(10):
            await store.record_memory_event(_make_action_event(action_type=f"tool.alpha_{i}"))

        results = await store.bm25_search("tool", limit=3)
        assert len(results) <= 3


class TestL4BackfillFTS:
    @pytest.mark.asyncio
    async def test_backfill_indexes_existing_skills(self, store):
        import aiosqlite

        # Insert directly into procedural_skills without FTS sync
        now = time.time()
        skill_id = "skill_test123"
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute(
                """INSERT INTO procedural_skills(
                    skill_id, skill_name, skill_category, skill_type, proficiency,
                    total_attempts, success_count, failure_count, success_rate,
                    avg_execution_time_ms, min_execution_time_ms, max_execution_time_ms, p95_execution_time_ms,
                    circuit_breaker_state, circuit_breaker_opened_at, circuit_breaker_failure_count,
                    circuit_breaker_success_count, optimized_prompt, optimized_params, optimization_score,
                    context_affinity, source_event_ids, last_used_at, last_success_at, last_failure_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    skill_id, "deploy.kubernetes", "devops", "external_tool", 1.0,
                    1, 1, 0, 1.0,
                    100.0, 100.0, 100.0, 100.0,
                    "closed", None, 0,
                    0, None, "{}", None,
                    "{}", '["evt-1"]', now, now, None,
                    now, now,
                ),
            )
            await db.commit()

        # Should not be in FTS
        results = await store.bm25_search("kubernetes")
        assert results == []

        # Backfill
        indexed = await store.backfill_fts()
        assert indexed == 1

        # Now searchable
        results = await store.bm25_search("kubernetes")
        assert len(results) == 1
        assert results[0][0] == skill_id

    @pytest.mark.asyncio
    async def test_backfill_skips_already_indexed(self, store):
        await store.record_memory_event(_make_action_event(action_type="already.indexed"))
        indexed = await store.backfill_fts()
        assert indexed == 0
