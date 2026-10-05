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
    async def test_updated_skill_replaces_old_search_terms(self, store):
        import aiosqlite

        first = _make_action_event(action_type="file.read")
        first.content = "obsoletecanary"
        skill_id = await store.record_memory_event(first)
        assert [row[0] for row in await store.bm25_search("obsoletecanary")] == [skill_id]
        second = _make_action_event(action_type="file.read")
        second.content = "currentcanary"
        assert await store.record_memory_event(second) == skill_id
        assert [row[0] for row in await store.bm25_search("currentcanary")] == [skill_id]
        assert await store.bm25_search("obsoletecanary") == []
        async with aiosqlite.connect(store.db_path) as db:
            assert await (await db.execute("SELECT skill_id FROM l4_skills_fts")).fetchall() == [
                (skill_id,)
            ]


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
    async def test_bm25_returns_only_matching_skills(self, store):
        opened = await store.record_memory_event(_make_action_event(action_type="browser.open"))
        unrelated = await store.record_memory_event(_make_action_event(action_type="file.write"))
        navigated = await store.record_memory_event(_make_action_event(action_type="browser.navigate"))
        ids = [row[0] for row in await store.bm25_search("browser")]
        assert len(ids) == 2 and set(ids) == {opened, navigated}
        assert unrelated not in ids

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
    async def test_search_limit_returns_exact_distinct_matches(self, store):
        known = {
            await store.record_memory_event(_make_action_event(action_type=f"tool.alpha_{i}"))
            for i in range(5)
        }
        ids = [row[0] for row in await store.bm25_search("tool", limit=3)]
        assert len(ids) == len(set(ids)) == 3
        assert set(ids) <= known


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
                    skill_id,
                    "deploy.kubernetes",
                    "devops",
                    "external_tool",
                    1.0,
                    1,
                    1,
                    0,
                    1.0,
                    100.0,
                    100.0,
                    100.0,
                    100.0,
                    "closed",
                    None,
                    0,
                    0,
                    None,
                    "{}",
                    None,
                    "{}",
                    '["evt-1"]',
                    now,
                    now,
                    None,
                    now,
                    now,
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

        assert await store.backfill_fts() == 0
        assert [row[0] for row in await store.bm25_search("kubernetes")] == [skill_id]
        async with aiosqlite.connect(store.db_path) as db:
            assert await (await db.execute("SELECT skill_id FROM l4_skills_fts")).fetchall() == [
                (skill_id,)
            ]
