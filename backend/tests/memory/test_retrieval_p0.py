"""Tests for P0 retrieval enhancements.

Covers:
- l1_event_entities schema creation
- write_event_entities / expand_by_entities in L1EventStore
- L1Handler 4-way RRF with entity expansion
- Service._augment_primary_plans L1 always-present guarantee
- Temporal pre-filter in L1Handler._fetch_and_filter
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.l1.event_store import L1EventStore
from magi.memory.hybrid_retrieval.handlers import L1Handler, rrf_fuse
from magi.memory.hybrid_retrieval.models import (
    L1Conditions,
    L2Conditions,
    LayerQueryPlan,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
    TimeRange,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _make_store(tmp_path):
    db_path = tmp_path / "l1_events.db"
    return L1EventStore(db_path=str(db_path))


async def _insert_event(store: L1EventStore, event_id: str, content: str, ts: float = 1000.0, user_id: str = "u1"):
    """Insert a minimal event through the store API.

    The raw ``fact_events`` shape is alembic-owned and has drifted from the
    old hand-rolled INSERT (``correlation_id``/``ingest_target`` are no
    longer columns), so go through the normal write path instead.
    """
    from magi.events.events import Event, EventLevel, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event

    event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": user_id, "session_id": "s1", "content": content},
            source="chat",
            level=EventLevel.INFO,
            correlation_id=event_id,
            metadata={"user_id": user_id},
            timestamp=ts,
            event_id=event_id,
        )
    )
    await store.store(event)


# -----------------------------------------------------------------------
# l1_event_entities schema
# -----------------------------------------------------------------------


class TestL1EventEntitiesSchema:
    @pytest.mark.asyncio
    async def test_table_created_on_initialize(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            from magi.core.sqlite import sqlite_connection_async

            async with sqlite_connection_async(store.db_path) as db:
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='l1_event_entities'"
                ) as cur:
                    row = await cur.fetchone()
            assert row is not None, "l1_event_entities table should exist after initialize"
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_indexes_created(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            from magi.core.sqlite import sqlite_connection_async

            async with sqlite_connection_async(store.db_path) as db:
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_l1_event_entities%'"
                ) as cur:
                    rows = await cur.fetchall()
            index_names = {row[0] for row in rows}
            # idx_l1_event_entities_event was intentionally DROPPED
            # (migration 11aa7f4e): UNIQUE(event_id, entity_id) already serves
            # every WHERE event_id = ? lookup. Only the entity-column index
            # (non-prefix column) remains.
            assert "idx_l1_event_entities_event" not in index_names
            assert "idx_l1_event_entities_entity" in index_names
        finally:
            await store.shutdown()


# -----------------------------------------------------------------------
# write_event_entities
# -----------------------------------------------------------------------


class TestWriteEventEntities:
    @pytest.mark.asyncio
    async def test_write_and_read_back(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            count = await store.write_event_entities([
                ("evt-1", "entity:alice", "person", 0.95),
                ("evt-1", "entity:python", "topic", 0.8),
                ("evt-2", "entity:alice", "person", 0.9),
            ])
            assert count == 3

            from magi.core.sqlite import sqlite_connection_async

            async with sqlite_connection_async(store.db_path) as db:
                async with db.execute("SELECT COUNT(*) FROM l1_event_entities") as cur:
                    total = (await cur.fetchone())[0]
            assert total == 3
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_duplicate_ignored(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            await store.write_event_entities([
                ("evt-1", "entity:alice", "person", 0.95),
            ])
            # Write same pair again
            await store.write_event_entities([
                ("evt-1", "entity:alice", "person", 0.99),
            ])

            from magi.core.sqlite import sqlite_connection_async

            async with sqlite_connection_async(store.db_path) as db:
                async with db.execute("SELECT COUNT(*) FROM l1_event_entities") as cur:
                    total = (await cur.fetchone())[0]
            assert total == 1
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            count = await store.write_event_entities([])
            assert count == 0
        finally:
            await store.shutdown()


# -----------------------------------------------------------------------
# expand_by_entities
# -----------------------------------------------------------------------


class TestExpandByEntities:
    @pytest.mark.asyncio
    async def test_expands_via_shared_entities(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            # evt-1 and evt-2 share "entity:alice"
            # evt-3 shares "entity:python" with evt-1
            await store.write_event_entities([
                ("evt-1", "entity:alice", "person", 0.9),
                ("evt-1", "entity:python", "topic", 0.8),
                ("evt-2", "entity:alice", "person", 0.9),
                ("evt-3", "entity:python", "topic", 0.7),
            ])

            # Seeds = [evt-1]; should find evt-2 (shares alice) and evt-3 (shares python)
            expanded = await store.expand_by_entities(["evt-1"], limit=10)
            assert set(expanded) == {"evt-2", "evt-3"}
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_excludes_seed_events(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            await store.write_event_entities([
                ("evt-1", "entity:x", "topic", 1.0),
                ("evt-2", "entity:x", "topic", 1.0),
            ])

            expanded = await store.expand_by_entities(["evt-1"], limit=10)
            assert "evt-1" not in expanded
            assert "evt-2" in expanded
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_orders_by_shared_count_desc(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            # evt-1 has entities A and B
            # evt-2 shares both A and B (shared_count=2)
            # evt-3 shares only A (shared_count=1)
            await store.write_event_entities([
                ("evt-1", "entity:a", "topic", 1.0),
                ("evt-1", "entity:b", "topic", 1.0),
                ("evt-2", "entity:a", "topic", 1.0),
                ("evt-2", "entity:b", "topic", 1.0),
                ("evt-3", "entity:a", "topic", 1.0),
            ])

            expanded = await store.expand_by_entities(["evt-1"], limit=10)
            assert expanded[0] == "evt-2"  # higher shared count
            assert expanded[1] == "evt-3"
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            await store.write_event_entities([
                ("evt-1", "entity:x", "topic", 1.0),
                ("evt-2", "entity:x", "topic", 1.0),
                ("evt-3", "entity:x", "topic", 1.0),
                ("evt-4", "entity:x", "topic", 1.0),
            ])

            expanded = await store.expand_by_entities(["evt-1"], limit=2)
            assert len(expanded) == 2
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_empty_seeds_returns_empty(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            expanded = await store.expand_by_entities([], limit=10)
            assert expanded == []
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_no_entity_links_returns_empty(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            expanded = await store.expand_by_entities(["evt-nonexistent"], limit=10)
            assert expanded == []
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_exclude_event_ids(self, tmp_path):
        store = _make_store(tmp_path)
        await store.initialize()
        try:
            await store.write_event_entities([
                ("evt-1", "entity:x", "topic", 1.0),
                ("evt-2", "entity:x", "topic", 1.0),
                ("evt-3", "entity:x", "topic", 1.0),
            ])

            expanded = await store.expand_by_entities(
                ["evt-1"], limit=10, exclude_event_ids=["evt-2"],
            )
            assert "evt-2" not in expanded
            assert "evt-3" in expanded
        finally:
            await store.shutdown()


# -----------------------------------------------------------------------
# L1Handler entity expansion integration
# -----------------------------------------------------------------------


class TestL1HandlerEntityExpansion:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("e1", -1.0), ("e2", -0.5)]
        s.vector_search.return_value = []
        s.query_events.return_value = []
        s.expand_by_entities.return_value = []
        s.resolve_event_entities.return_value = []
        s.find_events_by_entities.return_value = []
        s.filter_ids_by_user.return_value = []
        s.fetch_events.return_value = []
        return s

    @pytest.mark.asyncio
    async def test_calls_expand_by_entities_with_seed_ids(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="test query", limit=5)

        async def _bm25(q, limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["e1", "e2"]

        async def _vector(q, limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["e3"]

        async def _keyword(c, limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _fetch(*, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None):
            return [{"event_id": eid, "content": "c", "timestamp": 1000.0} for eid in event_ids]

        monkeypatch.setattr(handler, "_bm25_path", _bm25)
        monkeypatch.setattr(handler, "_vector_path", _vector)
        monkeypatch.setattr(handler, "_keyword_path", _keyword)
        monkeypatch.setattr(handler, "_fetch_and_filter", _fetch)

        await handler.execute(conds)

        # expand_by_entities should have been called with seeds from BM25+vector
        store.expand_by_entities.assert_called_once()
        call_args = store.expand_by_entities.call_args
        seed_ids = call_args[0][0]
        assert "e1" in seed_ids
        assert "e2" in seed_ids
        assert "e3" in seed_ids

    @pytest.mark.asyncio
    async def test_entity_expanded_events_appear_in_results(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="test", limit=10)

        async def _bm25(q, limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["e1"]

        async def _vector(q, limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _keyword(c, limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None):
            return []

        store.expand_by_entities.return_value = ["e2"]

        async def _fetch(*, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None):
            return [{"event_id": eid, "content": "c", "timestamp": 1000.0} for eid in event_ids]

        monkeypatch.setattr(handler, "_bm25_path", _bm25)
        monkeypatch.setattr(handler, "_vector_path", _vector)
        monkeypatch.setattr(handler, "_keyword_path", _keyword)
        monkeypatch.setattr(handler, "_fetch_and_filter", _fetch)

        results = await handler.execute(conds)
        result_ids = [r["event_id"] for r in results]
        assert "e2" in result_ids

    @pytest.mark.asyncio
    async def test_rrf_weight_entity_used(self):
        """Entity expansion IDs contribute to RRF with the entity weight."""
        config = RetrievalConfig()
        assert config.rrf_weight_entity == 0.7

        # 4-way RRF: entity-only hit should still get a score
        fused = rrf_fuse(
            [[], [], [], ["entity-only"]],
            [1.0, 1.0, 0.5, 0.7],
            k=60,
        )
        scores = dict(fused)
        assert "entity-only" in scores
        assert scores["entity-only"] > 0

    @pytest.mark.asyncio
    async def test_entity_expansion_failure_is_handled(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="test", limit=5)

        async def _bm25(q, limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["e1"]

        async def _vector(q, limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _keyword(c, limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None):
            return []

        store.expand_by_entities.side_effect = RuntimeError("DB error")

        async def _fetch(*, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None):
            return [{"event_id": eid, "content": "c", "timestamp": 1000.0} for eid in event_ids]

        monkeypatch.setattr(handler, "_bm25_path", _bm25)
        monkeypatch.setattr(handler, "_vector_path", _vector)
        monkeypatch.setattr(handler, "_keyword_path", _keyword)
        monkeypatch.setattr(handler, "_fetch_and_filter", _fetch)

        # Should not raise, fallback to 3-way RRF
        results = await handler.execute(conds)
        assert len(results) > 0


# -----------------------------------------------------------------------
# Service._augment_primary_plans: L1 always present
# -----------------------------------------------------------------------


class TestL1AlwaysParticipates:
    def _make_service_stub(self):
        from magi.memory.hybrid_retrieval.service import HybridRetrievalService

        memory = MagicMock()
        memory.l1 = MagicMock()
        memory.l2 = MagicMock()
        memory.l2_entity_catalog = None
        memory.l3 = None
        memory.l4 = None
        svc = HybridRetrievalService.__new__(HybridRetrievalService)
        svc._memory = memory
        svc._config = RetrievalConfig()
        svc._l1 = MagicMock()
        svc._l2 = MagicMock()
        svc._l3 = None
        svc._l4 = None
        svc._result_fusion = MagicMock()
        svc._manifest_selector = MagicMock()
        svc._intent_decider = MagicMock()
        svc._config_getter = None
        svc._llm_provider_bridge = None
        return svc

    def test_injects_l1_when_missing(self):
        svc = self._make_service_stub()
        # Plans with only L2 — no L1
        plans = [
            LayerQueryPlan(
                layer="L2",
                conditions=L2Conditions(content_query="test"),
                is_fallback=False,
            ),
        ]
        request = RetrievalQuery(query="test", user_id=None, session_id=None, time_range={})
        payload = RetrievalPayload(trace={})

        augmented = svc._augment_primary_plans(plans, request=request, payload=payload)
        layers = [p.layer for p in augmented]
        assert "L1" in layers
        assert payload.trace.get("l1_always_injected") is True

    def test_does_not_duplicate_existing_l1(self):
        svc = self._make_service_stub()
        plans = [
            LayerQueryPlan(
                layer="L1",
                conditions=L1Conditions(content_query="test", limit=10),
                is_fallback=False,
            ),
        ]
        request = RetrievalQuery(query="test", user_id=None, session_id=None, time_range={})
        payload = RetrievalPayload(trace={})

        augmented = svc._augment_primary_plans(plans, request=request, payload=payload)
        l1_count = sum(1 for p in augmented if p.layer == "L1")
        assert l1_count == 1
        assert "l1_always_injected" not in payload.trace


# -----------------------------------------------------------------------
# Temporal pre-filter in _fetch_and_filter
# -----------------------------------------------------------------------


class TestTemporalPreFilter:
    @pytest.mark.asyncio
    async def test_time_range_filters_in_sql(self, tmp_path):
        """Events outside time_range should be excluded by the SQL query."""
        store = L1EventStore(db_path=str(tmp_path / "l1.db"))
        await store.initialize()
        try:
            await _insert_event(store, "evt-old", "old event", ts=100.0)
            await _insert_event(store, "evt-inrange", "in range event", ts=500.0)
            await _insert_event(store, "evt-new", "new event", ts=900.0)

            handler = L1Handler(store)
            results = await handler._fetch_and_filter(
                event_ids=["evt-old", "evt-inrange", "evt-new"],
                conditions=L1Conditions(content_query="event"),
                time_range=TimeRange(start=200.0, end=800.0),
                session_id=None,
                user_id=None,
            )
            result_ids = [r["event_id"] for r in results]
            assert "evt-inrange" in result_ids
            assert "evt-old" not in result_ids
            assert "evt-new" not in result_ids
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_time_range_filter_logs_dropped_candidate_ids(self, tmp_path, caplog):
        store = L1EventStore(db_path=str(tmp_path / "l1.db"))
        await store.initialize()
        try:
            await _insert_event(store, "evt-old", "old event", ts=100.0)
            await _insert_event(store, "evt-inrange", "in range event", ts=500.0)
            await _insert_event(store, "evt-new", "new event", ts=900.0)

            handler = L1Handler(store)
            with caplog.at_level(
                logging.DEBUG,
                logger="magi.memory.hybrid_retrieval.l1_paths",
            ):
                await handler._fetch_and_filter(
                    event_ids=["evt-old", "evt-inrange", "evt-new"],
                    conditions=L1Conditions(content_query="event"),
                    time_range=TimeRange(start=200.0, end=800.0),
                    session_id=None,
                    user_id=None,
                )

            assert "L1 fetch filters applied" in caplog.text
            assert "input_count=3" in caplog.text
            assert "output_count=1" in caplog.text
            assert "dropped_ids_sample=['evt-old', 'evt-new']" in caplog.text
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_no_time_range_returns_all(self, tmp_path):
        store = L1EventStore(db_path=str(tmp_path / "l1.db"))
        await store.initialize()
        try:
            await _insert_event(store, "evt-1", "event one", ts=100.0)
            await _insert_event(store, "evt-2", "event two", ts=500.0)

            handler = L1Handler(store)
            results = await handler._fetch_and_filter(
                event_ids=["evt-1", "evt-2"],
                conditions=L1Conditions(content_query="event"),
                time_range=None,
                session_id=None,
                user_id=None,
            )
            assert len(results) == 2
        finally:
            await store.shutdown()

    @pytest.mark.asyncio
    async def test_partial_time_range_start_only(self, tmp_path):
        store = L1EventStore(db_path=str(tmp_path / "l1.db"))
        await store.initialize()
        try:
            await _insert_event(store, "evt-old", "old", ts=100.0)
            await _insert_event(store, "evt-new", "new", ts=500.0)

            handler = L1Handler(store)
            results = await handler._fetch_and_filter(
                event_ids=["evt-old", "evt-new"],
                conditions=L1Conditions(content_query="event"),
                time_range=TimeRange(start=300.0, end=None),
                session_id=None,
                user_id=None,
            )
            result_ids = [r["event_id"] for r in results]
            assert "evt-new" in result_ids
            assert "evt-old" not in result_ids
        finally:
            await store.shutdown()
