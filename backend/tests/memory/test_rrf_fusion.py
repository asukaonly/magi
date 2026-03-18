"""Tests for RRF fusion and triple-path L1Handler."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from magi.memory.hybrid_retrieval.handlers import L1Handler, rrf_fuse
from magi.memory.hybrid_retrieval.models import (
    L1Conditions,
    RetrievalConfig,
    TimeRange,
)
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l1.event_store import L1EventStore


# ---------------------------------------------------------------------------
# rrf_fuse unit tests
# ---------------------------------------------------------------------------


class TestRrfFuse:
    def test_single_list(self) -> None:
        results = rrf_fuse([["a", "b", "c"]], [1.0], k=60)
        ids = [r[0] for r in results]
        assert ids == ["a", "b", "c"]

    def test_two_agreeing_lists(self) -> None:
        results = rrf_fuse(
            [["a", "b", "c"], ["a", "b", "c"]],
            [1.0, 1.0],
            k=60,
        )
        ids = [r[0] for r in results]
        assert ids[0] == "a"
        assert ids[1] == "b"
        assert ids[2] == "c"

    def test_two_disagreeing_lists(self) -> None:
        # List 1: a > b > c > d; List 2: d > c > b > a
        results = rrf_fuse(
            [["a", "b", "c", "d"], ["d", "c", "b", "a"]],
            [1.0, 1.0],
            k=60,
        )
        ids = [r[0] for r in results]
        # Middle elements (b, c) get best combined rank
        # b: 1/62 + 1/62; c: 1/63 + 1/62 (symmetric for c too)
        # Actually b = 1/62 + 1/63 ≈ 0.03200, c = 1/63 + 1/62 ≈ 0.03200
        # All middle items have similar scores; verify all present
        assert set(ids) == {"a", "b", "c", "d"}

    def test_weighted_lists(self) -> None:
        # Give heavy weight to list 2 which ranks "x" first
        results = rrf_fuse(
            [["a", "b"], ["x", "a"]],
            [0.5, 2.0],
            k=60,
        )
        ids = [r[0] for r in results]
        assert ids[0] == "x" or ids[0] == "a"  # x gets 2.0/61, a gets 0.5/61 + 2.0/62
        # Actually: x score = 2.0/61 ≈ 0.0328; a score = 0.5/61 + 2.0/62 ≈ 0.0082 + 0.0323 = 0.0405
        assert ids[0] == "a"

    def test_empty_lists(self) -> None:
        results = rrf_fuse([[], []], [1.0, 1.0], k=60)
        assert results == []

    def test_disjoint_lists(self) -> None:
        results = rrf_fuse(
            [["a"], ["b"]],
            [1.0, 1.0],
            k=60,
        )
        ids = [r[0] for r in results]
        assert set(ids) == {"a", "b"}
        # Both rank 1 with equal weight, so equal scores
        assert abs(results[0][1] - results[1][1]) < 1e-10

    def test_k_parameter_affects_scores(self) -> None:
        r1 = rrf_fuse([["a"]], [1.0], k=1)
        r2 = rrf_fuse([["a"]], [1.0], k=100)
        # Smaller k → higher score for top ranks
        assert r1[0][1] > r2[0][1]

    def test_three_lists(self) -> None:
        results = rrf_fuse(
            [["a", "b", "c"], ["b", "c", "a"], ["c", "a", "b"]],
            [1.0, 1.0, 0.5],
            k=60,
        )
        assert len(results) == 3
        # All three items present
        assert set(r[0] for r in results) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# L1Handler triple-path integration tests (with real L1EventStore)
# ---------------------------------------------------------------------------


def _make_event(
    event_id: str = "evt-001",
    raw_content: str = "test content",
    source: str = "test",
    memory_domain: MemoryDomain = MemoryDomain.USER_AUTHORED,
    timestamp: float | None = None,
) -> MemoryEvent:
    now = timestamp or time.time()
    return MemoryEvent(
        event_id=event_id,
        correlation_id="corr-001",
        parent_event_id=None,
        timestamp=now,
        created_at=now,
        event_type="TestEvent",
        source=source,
        source_item_id=None,
        memory_domain=memory_domain,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=False,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        user_id=None,
        task_id=None,
        goal_id=None,
        raw_content=raw_content,
        structured_payload="{}",
        metadata="{}",
        importance_score=0.5,
        importance_t0_base=0.5,
        importance_t1_score=None,
        importance_version=1,
        level=1,
    )


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_l1.db"
    return L1EventStore(db_path=str(db), vector_enabled=False)


@pytest.mark.asyncio
class TestL1HandlerTriplePath:
    async def test_bm25_path_returns_results(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-py", raw_content="Python programming tutorial"))
        await store.store(_make_event(event_id="evt-js", raw_content="JavaScript web development"))

        handler = L1Handler(store)
        conds = L1Conditions(content_query="Python", limit=10)
        results = await handler.execute(conds)

        # Should find the Python event via BM25 (vector disabled)
        assert len(results) >= 1
        event_ids = [r["event_id"] for r in results]
        assert "evt-py" in event_ids

    async def test_empty_query_returns_empty(self, store: L1EventStore) -> None:
        await store.store(_make_event(raw_content="some content"))
        handler = L1Handler(store)
        conds = L1Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []

    async def test_time_range_filter(self, store: L1EventStore) -> None:
        base = 1700000000.0
        await store.store(_make_event(event_id="evt-old", raw_content="old event data", timestamp=base))
        await store.store(_make_event(event_id="evt-new", raw_content="new event data", timestamp=base + 1000))

        handler = L1Handler(store)
        conds = L1Conditions(content_query="event data", limit=10)
        tr = TimeRange(start=base + 500, end=base + 2000)
        results = await handler.execute(conds, tr)

        event_ids = [r["event_id"] for r in results]
        assert "evt-new" in event_ids
        assert "evt-old" not in event_ids

    async def test_limit_respected(self, store: L1EventStore) -> None:
        for i in range(10):
            await store.store(_make_event(
                event_id=f"evt-{i:03d}",
                raw_content=f"shared keyword content {i}",
            ))

        handler = L1Handler(store)
        conds = L1Conditions(content_query="shared keyword", limit=3)
        results = await handler.execute(conds)
        assert len(results) <= 3

    async def test_no_results_for_unmatched_query(self, store: L1EventStore) -> None:
        await store.store(_make_event(raw_content="hello world"))
        handler = L1Handler(store)
        conds = L1Conditions(content_query="quantumphysics", limit=10)
        results = await handler.execute(conds)
        assert results == []

    async def test_chinese_search(self, store: L1EventStore) -> None:
        await store.store(_make_event(event_id="evt-ml", raw_content="机器学习模型训练优化方案"))
        await store.store(_make_event(event_id="evt-web", raw_content="前端组件开发框架设计"))

        handler = L1Handler(store)
        conds = L1Conditions(content_query="机器学习", limit=10)
        results = await handler.execute(conds)

        event_ids = [r["event_id"] for r in results]
        assert "evt-ml" in event_ids

    async def test_config_passed_to_handler(self, store: L1EventStore) -> None:
        cfg = RetrievalConfig(rrf_k=10, rrf_weight_bm25=2.0, rrf_weight_vector=0.5, rrf_weight_keyword=0.3)
        handler = L1Handler(store, config=cfg)
        assert handler._config.rrf_k == 10
        assert handler._config.rrf_weight_bm25 == 2.0

    async def test_degraded_when_single_path_fails(self, store: L1EventStore) -> None:
        """Handler should still return results if one path fails."""
        await store.store(_make_event(event_id="evt-1", raw_content="test content data"))

        handler = L1Handler(store)

        # Monkeypatch BM25 to raise
        original_bm25 = handler._bm25_path

        async def failing_bm25(query, limit):
            raise RuntimeError("BM25 broken")

        handler._bm25_path = failing_bm25

        conds = L1Conditions(content_query="test content", limit=10)
        # Should not crash - keyword path should still work
        results = await handler.execute(conds)
        # keyword path should find it
        assert len(results) >= 1

    async def test_excludes_runtime_telemetry_by_default(self, store: L1EventStore) -> None:
        await store.store(_make_event(
            event_id="evt-rt",
            raw_content="runtime telemetry data",
            memory_domain=MemoryDomain.RUNTIME_TELEMETRY,
        ))
        await store.store(_make_event(
            event_id="evt-ua",
            raw_content="user authored data",
            memory_domain=MemoryDomain.USER_AUTHORED,
        ))

        handler = L1Handler(store)
        conds = L1Conditions(content_query="data", limit=10)
        results = await handler.execute(conds)

        event_ids = [r["event_id"] for r in results]
        # Runtime telemetry events go to runtime_observations table, not fact_events
        # so they shouldn't appear here at all
        assert "evt-rt" not in event_ids
