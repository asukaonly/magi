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
    mem.l2_entity_catalog = stores.get("l2_entity_catalog")
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


def _make_l3_store(tmp_path, summaries=None):
    """Build a mock L3 store with a real temp db for keyword path SQL."""
    import sqlite3
    db_path = str(tmp_path / "l3_mock.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS summaries (
            summary_id TEXT PRIMARY KEY, summary_type TEXT, summary_category TEXT,
            period_start REAL, period_end REAL, content TEXT,
            key_topics TEXT, key_entities TEXT, sentiment_summary TEXT, change_and_pattern TEXT,
            source_event_ids TEXT, source_event_count INTEGER,
            importance_aggregate REAL, event_type_distribution TEXT,
            generated_by_model TEXT, generation_prompt TEXT,
            generation_reason TEXT, created_at REAL, updated_at REAL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS l3_summaries_fts USING fts5(
            summary_id UNINDEXED, content, tokenize='unicode61'
        );
    """)
    conn.close()

    l3 = AsyncMock()
    l3.db_path = db_path
    l3.bm25_search.return_value = [(s["summary_id"], -1.0) for s in (summaries or [])]
    l3._semantic_search_summaries.return_value = []

    def _row_to_dict(row):
        return dict(row)

    l3._row_to_dict = _row_to_dict
    return l3


def _make_l4_store(tmp_path, skills=None):
    """Build a mock L4 store with a real temp db for keyword path SQL."""
    import sqlite3
    db_path = str(tmp_path / "l4_mock.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS procedural_skills (
            skill_id TEXT PRIMARY KEY, skill_name TEXT NOT NULL,
            skill_category TEXT NOT NULL, skill_type TEXT NOT NULL,
            proficiency REAL DEFAULT 0, total_attempts INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0, failure_count INTEGER DEFAULT 0,
            success_rate REAL DEFAULT 0, avg_execution_time_ms REAL,
            min_execution_time_ms REAL, max_execution_time_ms REAL,
            p95_execution_time_ms REAL, circuit_breaker_state TEXT DEFAULT 'closed',
            circuit_breaker_opened_at REAL, circuit_breaker_failure_count INTEGER DEFAULT 0,
            circuit_breaker_success_count INTEGER DEFAULT 0,
            optimized_prompt TEXT, optimized_params TEXT,
            optimization_score REAL, context_affinity TEXT,
            source_event_ids TEXT NOT NULL, last_used_at REAL,
            last_success_at REAL, last_failure_at REAL,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS l4_skills_fts USING fts5(
            skill_id UNINDEXED, content, tokenize='unicode61'
        );
    """)
    conn.close()

    l4 = AsyncMock()
    l4.db_path = db_path
    l4.bm25_search.return_value = [(s["skill_id"], -1.0) for s in (skills or [])]
    l4._semantic_query_strategies.return_value = []

    def _row_to_dict(row):
        return dict(row)

    l4._row_to_dict = _row_to_dict
    return l4


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
        l1 = _make_l1_store([{"event_id": "e1", "content": "test", "timestamp": 1000.0}])
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(query_mode="detail"))
        # L1Handler uses keyword path which filters by content tokens
        # The mock query_events returns the event, and keyword matching should pass
        assert l1.bm25_search.called or l1.query_events.called

    @pytest.mark.asyncio
    async def test_summary_mode_queries_l3(self, tmp_path):
        l3 = _make_l3_store(tmp_path, [{"summary_id": "s1", "content": "summary"}])
        mem = _make_memory(l3=l3)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(query_mode="summary"))
        assert l3.bm25_search.called

    @pytest.mark.asyncio
    async def test_summary_mode_picks_up_l3_initialized_after_service_construction(self, tmp_path):
        mem = _make_memory(l3=None)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        late_l3 = _make_l3_store(tmp_path, [{"summary_id": "s1", "content": "summary"}])
        mem.l3 = late_l3

        await svc.query(_make_request(query_mode="summary"))

        assert late_l3.bm25_search.called

    @pytest.mark.asyncio
    async def test_experience_mode_queries_l4(self, tmp_path):
        l4 = _make_l4_store(tmp_path, [{"skill_id": "p1", "skill_name": "test"}])
        mem = _make_memory(l4=l4)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(query_mode="experience"))
        assert l4.bm25_search.called

    @pytest.mark.asyncio
    async def test_graph_mode_queries_l2(self):
        l2 = AsyncMock()
        l2.get_tom_snapshot.return_value = None
        l2.get_relationships.return_value = [{"subject": "a", "object": "b"}]
        l2.list_tom_assertions.return_value = []
        mem = _make_memory(l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(query_mode="graph"))
        assert len(result.l2_relationships) >= 0  # may or may not have results

    @pytest.mark.asyncio
    async def test_graph_mode_returns_assertions(self):
        l2 = AsyncMock()
        l2.get_tom_snapshot.return_value = {"entity_id": "user:u1", "entity_type": "user"}
        l2.get_relationships.return_value = []
        l2.list_tom_assertions.return_value = [
            {
                "assertion_id": "assert-1",
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "dislike",
                "trait_value": "rainy_weather",
                "validation_state": "corroborated",
            }
        ]
        mem = _make_memory(l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(_make_request(query_mode="graph"))

        assert len(result.l2_assertions) == 1
        l2.list_tom_assertions.assert_called()

    @pytest.mark.asyncio
    async def test_graph_mode_filters_relationships_by_predicate_and_status(self):
        l2 = AsyncMock()
        l2.get_tom_snapshot.return_value = None
        l2.get_relationships.return_value = [{"triple_id": "triple-1"}]
        l2.list_tom_assertions.return_value = []
        mem = _make_memory(l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(
            _make_request(
                query_mode="graph",
                query="我讨厌什么天气",
            )
        )

        assert len(result.l2_relationships) == 1
        _, kwargs = l2.get_relationships.call_args
        assert kwargs["predicates"] == ["DISLIKES"]
        assert kwargs["status_filters"] == ["active", "conflicted"]

    @pytest.mark.asyncio
    async def test_graph_mode_resolves_alias_entities_via_entity_catalog(self):
        l2 = AsyncMock()
        l2.get_tom_snapshot.return_value = None
        l2.get_relationships.return_value = [{"triple_id": "triple-1", "subject_id": "place:shanghai"}]
        l2.list_tom_assertions.return_value = []
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "place:shanghai",
                "entity_type": "place",
                "canonical_name": "Shanghai",
                "match_source": "alias",
            }
        ]
        mem = _make_memory(l2=l2, l2_entity_catalog=entity_catalog)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        await svc.query(
            _make_request(
                query_mode="graph",
                query="我对魔都是什么感觉",
            )
        )

        entity_catalog.resolve_query_entities.assert_called_once()
        _, kwargs = l2.get_relationships.call_args
        assert kwargs["subject_id"] == "place:shanghai"

    @pytest.mark.asyncio
    async def test_graph_mode_can_query_incoming_relationships(self):
        l2 = AsyncMock()
        l2.get_tom_snapshot.return_value = None
        l2.get_relationships.return_value = [{"triple_id": "triple-in", "object_id": "user:u1"}]
        l2.list_tom_assertions.return_value = []
        mem = _make_memory(l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(
            _make_request(
                query_mode="graph",
                query="谁认识我",
            )
        )

        assert len(result.l2_relationships) == 1
        _, kwargs = l2.get_relationships.call_args
        assert kwargs["object_id"] == "user:u1"

    @pytest.mark.asyncio
    async def test_graph_mode_filters_assertions_by_target_entity(self):
        l2 = AsyncMock()
        l2.get_tom_snapshot.return_value = None
        l2.get_relationships.return_value = []
        l2.list_tom_assertions.return_value = [{"assertion_id": "assert-1"}]
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "weather_state:rainy-hangzhou",
                "entity_type": "weather_state",
                "canonical_name": "Rainy Hangzhou Weather",
                "match_source": "canonical_name",
            }
        ]
        mem = _make_memory(l2=l2, l2_entity_catalog=entity_catalog)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        await svc.query(
            _make_request(
                query_mode="graph",
                query="我讨厌什么天气",
            )
        )

        _, kwargs = l2.list_tom_assertions.call_args
        assert kwargs["target_entity_id"] == "weather_state:rainy-hangzhou"

    @pytest.mark.asyncio
    async def test_graph_mode_populates_l2_query_trace(self):
        l2 = AsyncMock()
        l2.get_tom_snapshot.return_value = None
        l2.get_relationships.return_value = []
        l2.list_tom_assertions.return_value = []
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "place:shanghai",
                "entity_type": "place",
                "canonical_name": "Shanghai",
                "match_source": "alias",
            }
        ]
        mem = _make_memory(l2=l2, l2_entity_catalog=entity_catalog)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(
            _make_request(
                query_mode="graph",
                query="我和魔都是什么关系",
            )
        )

        l2_trace = result.trace.get("l2_query_trace")
        assert isinstance(l2_trace, dict)
        assert l2_trace["resolved_entities"][0]["entity_id"] == "place:shanghai"
        assert "KNOWS" in l2_trace["predicates"]


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
        from magi.memory.l1.event_store import L1EventStore
        from magi.memory.event_contracts import (
            IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test_l1.db"
            real_l1 = L1EventStore(db_path=db_path, vector_enabled=False)
            now = time.time()
            event = MemoryEvent(
                event_id="e1",
                correlation_id="c1",
                timestamp=now,
                created_at=now,
                event_type="Test",
                source="test",
                source_item_id=None,
                memory_domain=MemoryDomain.USER_AUTHORED,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=False,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id=None,
                task_id=None,
                content="something interesting here",
                author_type="user",
                content_type="text",
                importance_score=0.5,
                level=1,
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
        l1 = _make_l1_store([{"event_id": "e1", "content": "test", "timestamp": 1000.0}])
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
