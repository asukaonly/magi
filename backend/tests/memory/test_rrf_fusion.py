"""Tests for RRF fusion and triple-path L1Handler."""

from __future__ import annotations

import time

import pytest

from magi.memory.hybrid_retrieval.handlers import L1Handler, rrf_fuse
from magi.memory.hybrid_retrieval.models import (
    L1Conditions,
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
    @pytest.mark.parametrize(
        "rankings,weights,k,expected",
        [
            ([["a", "b", "c"]], [1.0], 1, {"a": 0.5, "b": 1 / 3, "c": 0.25}),
            ([["a", "b", "c"], ["a", "b", "c"]], [1.0, 1.0], 1, {"a": 1.0, "b": 2 / 3, "c": 0.5}),
            (
                [["a", "b", "c", "d"], ["d", "c", "b", "a"]],
                [1.0, 1.0],
                1,
                {"a": 0.7, "d": 0.7, "b": 7 / 12, "c": 7 / 12},
            ),
            ([["a", "b"], ["b", "a"]], [1.0, 3.0], 1, {"b": 11 / 6, "a": 1.5}),
            ([["a", "b"], ["b", "a"]], [3.0, 1.0], 1, {"a": 11 / 6, "b": 1.5}),
            ([[], []], [1.0, 1.0], 60, {}),
            ([["a"], ["b"]], [1.0, 1.0], 1, {"a": 0.5, "b": 0.5}),
            ([["a"]], [1.0], 60, {"a": 1 / 61}),
            ([["a"]], [1.0], 100, {"a": 1 / 101}),
            (
                [["a", "b", "c"], ["b", "c", "a"], ["c", "a", "b"]],
                [1.0, 1.0, 0.5],
                1,
                {"b": 23 / 24, "a": 11 / 12, "c": 5 / 6},
            ),
        ],
        ids=[
            "single",
            "agreement-doubles",
            "disagreement",
            "second-weight-wins",
            "first-weight-wins",
            "empty",
            "disjoint-tie",
            "default-k",
            "large-k",
            "three-weighted-lists",
        ],
    )
    def test_fusion_has_exact_reciprocal_scores_and_descending_rank(
        self, rankings, weights, k, expected
    ):
        results = rrf_fuse(rankings, weights, k=k)
        assert len(results) == len(expected)
        assert dict(results) == pytest.approx(expected)
        assert [score for _, score in results] == pytest.approx(sorted(expected.values(), reverse=True))


# ---------------------------------------------------------------------------
# L1Handler triple-path integration tests (with real L1EventStore)
# ---------------------------------------------------------------------------


def _make_event(
    event_id: str = "evt-001",
    content: str = "test content",
    source: str = "test",
    memory_domain: MemoryDomain = MemoryDomain.USER_AUTHORED,
    timestamp: float | None = None,
) -> MemoryEvent:
    now = timestamp or time.time()
    return MemoryEvent(
        event_id=event_id,
        correlation_id="corr-001",
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
        turn_id=None,
        user_id=None,
        task_id=None,
        content=content,
        author_type="user",
        content_type="text",
        importance_score=0.5,
        level=1,
    )


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_l1.db"
    return L1EventStore(db_path=str(db), vector_enabled=False)


@pytest.mark.asyncio
class TestL1HandlerTriplePath:
    @pytest.mark.parametrize(
        "query,expected_ids",
        [("Python", ["evt-python"]), ("机器学习", ["evt-ml"]), ("", []), ("quantumphysics", [])],
        ids=["english", "chinese", "empty", "unmatched"],
    )
    async def test_lexical_retrieval_returns_only_matching_stored_events(
        self, store, query, expected_ids
    ):
        events = [
            _make_event(event_id="evt-python", content="Python programming tutorial"),
            _make_event(event_id="evt-js", content="JavaScript web development"),
            _make_event(event_id="evt-ml", content="机器学习模型训练优化方案"),
            _make_event(event_id="evt-web", content="前端组件开发框架设计"),
        ]
        for event in events:
            await store.store(event)
        results = await L1Handler(store).execute(L1Conditions(content_query=query, limit=10))
        assert [row["event_id"] for row in results] == expected_ids
        expected_content = {event.event_id: event.content for event in events}
        assert all(row["content"] == expected_content[row["event_id"]] for row in results)


    async def test_time_range_filter(self, store: L1EventStore) -> None:
        base = 1700000000.0
        await store.store(_make_event(event_id="evt-old", content="old event data", timestamp=base))
        await store.store(_make_event(event_id="evt-new", content="new event data", timestamp=base + 1000))

        handler = L1Handler(store)
        conds = L1Conditions(content_query="event data", limit=10)
        tr = TimeRange(start=base + 500, end=base + 2000)
        results = await handler.execute(conds, tr)

        event_ids = [r["event_id"] for r in results]
        assert "evt-new" in event_ids
        assert "evt-old" not in event_ids

    async def test_limit_returns_exact_number_of_distinct_eligible_ranked_events(self, store):
        for index in range(10):
            await store.store(
                _make_event(
                    event_id=f"evt-{index}",
                    content=f"shared keyword content {index}",
                    timestamp=1700000000.0 + index,
                )
            )
        await store.store(_make_event(event_id="unrelated", content="different topic"))
        results = await L1Handler(store).execute(L1Conditions(content_query="shared keyword", limit=3))
        assert len(results) == 3
        assert len({row["event_id"] for row in results}) == 3
        assert {row["event_id"] for row in results} <= {f"evt-{index}" for index in range(10)}
        assert [(row["event_id"], row["content"]) for row in results] == [
            (row["event_id"], "shared keyword content " + row["event_id"].removeprefix("evt-"))
            for row in results
        ]
        scores = [row["retrieval_score"] for row in results]
        assert scores == sorted(scores, reverse=True)


    async def test_degraded_when_single_path_fails(self, store: L1EventStore, monkeypatch) -> None:
        """Handler should still return results if one path fails."""
        await store.store(_make_event(event_id="evt-1", content="test content data"))

        handler = L1Handler(store)

        # Monkeypatch BM25 to raise

        async def failing_bm25(query, limit, *, user_id=None, l1_retrieval_scopes=None):
            raise RuntimeError("BM25 broken")

        monkeypatch.setattr(handler, "_bm25_path", failing_bm25)

        conds = L1Conditions(content_query="test content", limit=10)
        # Should not crash - keyword path should still work
        results = await handler.execute(conds)
        # keyword path should find it
        assert [(row["event_id"], row["content"]) for row in results] == [
            ("evt-1", "test content data")
        ]

    async def test_recall_reads_user_facts_without_runtime_observations(
        self, store: L1EventStore
    ) -> None:
        await store.store(
            _make_event(
                event_id="evt-rt",
                content="runtime telemetry data",
                memory_domain=MemoryDomain.RUNTIME_TELEMETRY,
            )
        )
        await store.store(
            _make_event(
                event_id="evt-ua",
                content="user authored data",
                memory_domain=MemoryDomain.USER_AUTHORED,
            )
        )

        handler = L1Handler(store)
        conds = L1Conditions(content_query="data", limit=10)
        results = await handler.execute(conds)

        event_ids = [r["event_id"] for r in results]
        # Runtime telemetry events go to runtime_observations table, not fact_events
        # so they shouldn't appear here at all
        assert event_ids == ["evt-ua"]
        assert results[0]["content"] == "user authored data"
