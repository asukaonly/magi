"""Tests for layer handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.handlers import (
    L1Handler,
    L2Handler,
    L3Handler,
    L4Handler,
    execute_plan,
)
from magi.memory.hybrid_retrieval.models import (
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    TimeRange,
)


# -----------------------------------------------------------------------
# L1Handler (mock-based, triple-path)
# -----------------------------------------------------------------------


class TestL1Handler:
    """Mock-based tests for L1Handler triple-path search.

    Full integration tests with real L1EventStore live in test_rrf_fusion.py.
    These tests verify interface behavior with mocked store methods.
    """

    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("e1", -1.0), ("e2", -0.5)]
        s._semantic_search_event_hits.return_value = []
        s.query_events.return_value = [
            {"event_id": "e1", "raw_content": "hello world", "timestamp": 1000},
            {"event_id": "e2", "raw_content": "world peace", "timestamp": 2000},
        ]
        return s

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []
        store.bm25_search.assert_not_called()


# -----------------------------------------------------------------------
# L2Handler
# -----------------------------------------------------------------------


class TestL2Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.get_tom_snapshot.return_value = {"entity_id": "alice", "name": "Alice"}
        s.get_relationships.return_value = [{"subject": "alice", "object": "bob"}]
        return s

    @pytest.mark.asyncio
    async def test_entity_cards(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=["alice"],
            include_tom_snapshot=True,
            include_relationships=False,
        )
        results = await handler.execute(conds)
        assert len(results["entity_cards"]) == 1
        assert results["entity_cards"][0]["entity_id"] == "alice"

    @pytest.mark.asyncio
    async def test_relationships(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=["alice"],
            include_tom_snapshot=False,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["relationships"]) == 1

    @pytest.mark.asyncio
    async def test_both_snapshot_and_relationships(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=["alice"],
            include_tom_snapshot=True,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["entity_cards"]) == 1
        assert len(results["relationships"]) == 1

    @pytest.mark.asyncio
    async def test_no_entities_gets_all_relationships(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=None,
            include_tom_snapshot=True,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["entity_cards"]) == 0  # no entities to snapshot
        store.get_relationships.assert_called_once()


# -----------------------------------------------------------------------
# L3Handler
# -----------------------------------------------------------------------


class TestL3Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("s1", -1.0)]
        s._semantic_search_summaries.return_value = [{"summary_id": "s1", "content": "weekly summary"}]
        return s

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L3Handler(store)
        conds = L3Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []
        store.bm25_search.assert_not_called()


# -----------------------------------------------------------------------
# L4Handler
# -----------------------------------------------------------------------


class TestL4Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("p1", -1.0)]
        s._semantic_query_strategies.return_value = [{"skill_id": "p1", "content": "deploy strategy"}]
        return s

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L4Handler(store)
        conds = L4Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []
        store.bm25_search.assert_not_called()
        results = await handler.execute(conds)
        assert results == []


# -----------------------------------------------------------------------
# execute_plan dispatch
# -----------------------------------------------------------------------


class TestExecutePlan:
    @pytest.mark.asyncio
    async def test_dispatch_l1(self):
        l1 = AsyncMock(spec=L1Handler)
        l1.execute.return_value = [{"id": "e1"}]
        plan = LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="x"))
        result = await execute_plan(plan, l1=l1)
        assert result == [{"id": "e1"}]

    @pytest.mark.asyncio
    async def test_dispatch_l2(self):
        l2 = AsyncMock(spec=L2Handler)
        l2.execute.return_value = {"entity_cards": [], "relationships": []}
        plan = LayerQueryPlan(layer="L2", conditions=L2Conditions())
        result = await execute_plan(plan, l2=l2)
        assert "entity_cards" in result

    @pytest.mark.asyncio
    async def test_dispatch_l3(self):
        l3 = AsyncMock(spec=L3Handler)
        l3.execute.return_value = [{"id": "s1"}]
        plan = LayerQueryPlan(layer="L3", conditions=L3Conditions(content_query="x"))
        result = await execute_plan(plan, l3=l3)
        assert result == [{"id": "s1"}]

    @pytest.mark.asyncio
    async def test_dispatch_l4(self):
        l4 = AsyncMock(spec=L4Handler)
        l4.execute.return_value = [{"id": "p1"}]
        plan = LayerQueryPlan(layer="L4", conditions=L4Conditions(content_query="x"))
        result = await execute_plan(plan, l4=l4)
        assert result == [{"id": "p1"}]

    @pytest.mark.asyncio
    async def test_missing_handler_returns_empty(self):
        plan = LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="x"))
        result = await execute_plan(plan)  # no handlers
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_l2_handler_returns_empty_dict(self):
        plan = LayerQueryPlan(layer="L2", conditions=L2Conditions())
        result = await execute_plan(plan)
        assert result == {"entity_cards": [], "relationships": []}
