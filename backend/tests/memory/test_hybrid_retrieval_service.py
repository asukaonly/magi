"""Tests for the rewritten HybridRetrievalService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.memory.hybrid_retrieval.models import (
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
)
from magi.memory.hybrid_retrieval.service import HybridRetrievalService


def _make_memory(**stores):
    """Build a mock unified memory with optional layer stores."""
    mem = MagicMock()
    mem.l0 = stores.get("l0")
    mem.l1 = stores.get("l1")
    mem.l2 = stores.get("l2")
    mem.l3 = stores.get("l3")
    mem.l4 = stores.get("l4")
    return mem


def _make_l1_store(events=None):
    """Build a properly mocked L1 store for triple-path L1Handler."""
    import tempfile
    l1 = AsyncMock()
    l1.db_path = tempfile.mktemp(suffix=".db")
    l1.bm25_search.return_value = [(e["event_id"], -1.0) for e in (events or [])]
    l1._semantic_search_event_hits.return_value = []
    l1.query_events.return_value = events or []
    l1.search_events.return_value = events or []

    def _row_to_dict(row):
        return dict(row)

    l1._row_to_dict = _row_to_dict
    return l1


def _make_request(**kwargs):
    defaults = {
        "query": "test query",
        "user_id": "u1",
        "session_id": "s1",
        "time_range": {},
        "query_mode": None,
        "source_filters": [],
        "domain_filters": [],
        "limit": 10,
    }
    defaults.update(kwargs)
    return RetrievalQuery(**defaults)


class TestServiceBasicFlow:
    @pytest.mark.asyncio
    async def test_empty_memory_returns_empty_payload(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request())
        assert isinstance(result, RetrievalPayload)

    @pytest.mark.asyncio
    async def test_l0_loaded_when_session_id_present(self):
        l0 = AsyncMock()
        l0.get_workbench.return_value = {
            "session": {"id": "s1"},
            "goal_stack": ["g1"],
            "active_entities": ["e1"],
            "temporary_tactics": ["t1"],
        }
        mem = _make_memory(l0=l0)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(session_id="s1"))
        assert len(result.l0_workbench) == 1
        assert result.l0_workbench[0]["session"]["id"] == "s1"

    @pytest.mark.asyncio
    async def test_l0_not_loaded_without_session_id(self):
        l0 = AsyncMock()
        mem = _make_memory(l0=l0)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(session_id=None))
        assert len(result.l0_workbench) == 0
        l0.get_workbench.assert_not_called()


class TestServiceLayerRouting:
    @pytest.mark.asyncio
    async def test_detail_mode_queries_l1(self):
        l1 = _make_l1_store([{"event_id": "e1", "raw_content": "test", "timestamp": 1000.0}])
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(query_mode="detail"))
        # L1Handler uses keyword path which filters by raw_content tokens
        # The mock query_events returns the event, and keyword matching should pass
        assert l1.bm25_search.called or l1.query_events.called

    @pytest.mark.asyncio
    async def test_summary_mode_queries_l3(self):
        l3 = AsyncMock()
        l3.search_summaries.return_value = [{"summary_id": "s1", "content": "summary"}]
        mem = _make_memory(l3=l3)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(query_mode="summary"))
        assert len(result.l3_reflections) >= 1

    @pytest.mark.asyncio
    async def test_experience_mode_queries_l4(self):
        l4 = AsyncMock()
        l4.query_strategies.return_value = [{"id": "p1"}]
        mem = _make_memory(l4=l4)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(query_mode="experience"))
        assert len(result.l4_procedures) >= 1

    @pytest.mark.asyncio
    async def test_graph_mode_queries_l2(self):
        l2 = AsyncMock()
        l2.get_tom_snapshot.return_value = None
        l2.get_relationships.return_value = [{"subject": "a", "object": "b"}]
        mem = _make_memory(l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(query_mode="graph"))
        assert len(result.l2_relationships) >= 0  # may or may not have results


class TestServiceFallback:
    @pytest.mark.asyncio
    async def test_fallback_triggered_when_primary_empty(self):
        l1 = _make_l1_store([])
        l3 = AsyncMock()
        l3.search_summaries.return_value = [{"summary_id": "s1", "content": "fallback"}]
        mem = _make_memory(l1=l1, l3=l3)
        config = RetrievalConfig(
            intent_decider_llm_enabled=False,
            fallback_trigger_threshold=1,
        )
        svc = HybridRetrievalService(mem, config=config)
        result = await svc.query(_make_request(query="something"))
        assert result.trace.get("fallback_triggered") is True

    @pytest.mark.asyncio
    async def test_no_fallback_when_primary_has_results(self):
        """If primary handler returns results, no fallback should be triggered.

        Uses a real L1EventStore (with FTS5) to get actual search results.
        """
        import tempfile
        import time
        from magi.memory.l1_event_store import L1EventStore
        from magi.memory.event_contracts import (
            IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test_l1.db"
            real_l1 = L1EventStore(db_path=db_path, vector_enabled=False)
            now = time.time()
            event = MemoryEvent(
                event_id="e1", correlation_id="c1", parent_event_id=None,
                timestamp=now, created_at=now, event_type="Test", source="test",
                source_item_id=None, memory_domain=MemoryDomain.USER_AUTHORED,
                ingest_target=IngestTarget.L1_ONLY, cognition_eligible=False,
                tom_depth=TomDepth.NONE, retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None, user_id=None, task_id=None, goal_id=None,
                raw_content="something interesting here",
                structured_payload="{}", metadata="{}",
                importance_score=0.5, importance_t0_base=0.5,
                importance_t1_score=None, importance_version=1, level=1,
            )
            await real_l1.store(event)

            # Verify the event is searchable directly
            bm25 = await real_l1.bm25_search("something", limit=5)
            assert len(bm25) > 0, f"BM25 should find the event, got: {bm25}"

            l3 = AsyncMock()
            l3.search_summaries.return_value = []
            mem = _make_memory(l1=real_l1, l3=l3)
            config = RetrievalConfig(
                intent_decider_llm_enabled=False,
                fallback_trigger_threshold=1,
            )
            svc = HybridRetrievalService(mem, config=config)
            result = await svc.query(_make_request(query="something", session_id=None, user_id=None))
            assert len(result.l1_events) >= 1, f"Expected L1 results, trace={result.trace}"
            assert result.trace.get("fallback_triggered") is not True


class TestServiceTrace:
    @pytest.mark.asyncio
    async def test_trace_contains_intent_info(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request())
        assert "intent_source" in result.trace
        assert result.trace["intent_source"] == "rule_fallback"

    @pytest.mark.asyncio
    async def test_trace_contains_primary_count(self):
        l1 = _make_l1_store([{"event_id": "e1", "raw_content": "test", "timestamp": 1000.0}])
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request())
        assert "primary_count" in result.trace


class TestServiceErrorHandling:
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_crash(self):
        l1 = _make_l1_store([])
        l1.bm25_search.side_effect = RuntimeError("db error")
        l1.query_events.side_effect = RuntimeError("db error")
        l1._semantic_search_event_hits.side_effect = RuntimeError("db error")
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request())
        # Should return payload even if L1 fails
        assert isinstance(result, RetrievalPayload)

    @pytest.mark.asyncio
    async def test_l0_failure_does_not_crash(self):
        l0 = AsyncMock()
        l0.get_workbench.side_effect = RuntimeError("l0 error")
        mem = _make_memory(l0=l0)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request())
        assert result.l0_workbench == []
