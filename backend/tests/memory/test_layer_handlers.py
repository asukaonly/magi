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
# L1Handler
# -----------------------------------------------------------------------


class TestL1Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.search_events.return_value = [
            {"event_id": "e1", "timestamp": 1000, "content": "hello"},
            {"event_id": "e2", "timestamp": 2000, "content": "world"},
        ]
        return s

    @pytest.mark.asyncio
    async def test_basic_search(self, store):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="hello", limit=10)
        results = await handler.execute(conds)
        assert len(results) == 2
        store.search_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_time_range_filter(self, store):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="hello")
        tr = TimeRange(start=1500, end=2500)
        results = await handler.execute(conds, tr)
        assert len(results) == 1
        assert results[0]["event_id"] == "e2"

    @pytest.mark.asyncio
    async def test_source_domain_passed(self, store):
        handler = L1Handler(store)
        conds = L1Conditions(
            content_query="test",
            source_filters=["browser"],
            domain_filters=["web"],
        )
        await handler.execute(conds, session_id="s1", user_id="u1")
        call_kwargs = store.search_events.call_args.kwargs
        assert call_kwargs["source_filters"] == ["browser"]
        assert call_kwargs["domain_filters"] == ["web"]
        assert call_kwargs["session_id"] == "s1"
        assert call_kwargs["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []
        store.search_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_type_passed(self, store):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="test", event_types=["browse"])
        await handler.execute(conds)
        assert store.search_events.call_args.kwargs["event_type"] == "browse"


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
        s.search_summaries.return_value = [{"id": "s1", "content": "weekly summary"}]
        return s

    @pytest.mark.asyncio
    async def test_basic_search(self, store):
        handler = L3Handler(store)
        conds = L3Conditions(content_query="weekly", limit=5)
        results = await handler.execute(conds)
        assert len(results) == 1
        store.search_summaries.assert_called_once_with(
            query="weekly",
            summary_type=None,
            limit=5,
        )

    @pytest.mark.asyncio
    async def test_summary_type_passed(self, store):
        handler = L3Handler(store)
        conds = L3Conditions(content_query="review", summary_types=["weekly"])
        await handler.execute(conds)
        assert store.search_summaries.call_args.kwargs["summary_type"] == "weekly"

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L3Handler(store)
        conds = L3Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []


# -----------------------------------------------------------------------
# L4Handler
# -----------------------------------------------------------------------


class TestL4Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.query_strategies.return_value = [{"id": "p1", "content": "deploy strategy"}]
        return s

    @pytest.mark.asyncio
    async def test_basic_search(self, store):
        handler = L4Handler(store)
        conds = L4Conditions(content_query="deploy", limit=5)
        results = await handler.execute(conds)
        assert len(results) == 1
        store.query_strategies.assert_called_once_with(query="deploy", limit=5)

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L4Handler(store)
        conds = L4Conditions(content_query="")
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
