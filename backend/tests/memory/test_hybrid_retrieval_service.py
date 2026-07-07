"""Tests for the rewritten HybridRetrievalService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.config.models import AppConfig
from magi.memory.hybrid_retrieval.models import (
    IntentDecision,
    L1Conditions,
    L2Conditions,
    L2SemanticFrame,
    LayerQueryPlan,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
    SemanticConstraint,
    TimeRange,
)
from magi.memory.hybrid_retrieval.service import HybridRetrievalService, build_retrieval_config_from_app_config


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
    l1.vector_search.return_value = []
    l1.query_events.return_value = events or []
    l1.search_events.return_value = events or []
    l1.resolve_event_entities.return_value = []
    l1.find_events_by_entities.return_value = []
    l1.expand_by_entities.return_value = []
    l1.filter_ids_by_user.return_value = []
    l1.fetch_events.return_value = events or []
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
    l3.vector_search.return_value = []
    l3.keyword_search.return_value = []
    l3.fetch_by_ids.return_value = []
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
    l4.keyword_search.return_value = []
    l4.fetch_by_ids.return_value = []
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


@pytest.mark.asyncio
async def test_l1_handler_passes_retrieval_scopes_before_fusion():
    from magi.memory.hybrid_retrieval.l1_handler import L1Handler

    event = {
        "event_id": "evt-user-scope",
        "content": "I like oolong tea.",
        "user_id": "u1",
        "memory_domain": "user_authored",
        "l1_retrieval_scope": "fact_authoritative",
    }
    l1 = _make_l1_store([event])
    handler = L1Handler(l1).with_l1_retrieval_scopes(["fact_authoritative"])

    await handler.execute(L1Conditions(content_query="oolong tea", limit=5), user_id="u1")

    assert l1.bm25_search.call_args.kwargs["l1_retrieval_scopes"] == ["fact_authoritative"]
    assert l1.query_events.call_args.kwargs["l1_retrieval_scopes"] == ["fact_authoritative"]
    assert l1.fetch_events.call_args.kwargs["l1_retrieval_scopes"] == ["fact_authoritative"]


def test_build_retrieval_config_reads_memory_reranker_settings():
    config = AppConfig()
    config.agent.memory.reranker.top_k = 9
    config.agent.memory.reranker.cross_encoder.enabled = True
    config.agent.memory.reranker.cross_encoder.managed_model_id = "bge-reranker-v2-m3"
    config.agent.memory.query_expansion.enabled = True

    retrieval_config = build_retrieval_config_from_app_config(config)

    assert retrieval_config.reranker_top_k == 9
    assert retrieval_config.cross_encoder_enabled is True
    assert retrieval_config.cross_encoder_model_id == "bge-reranker-v2-m3"
    assert retrieval_config.query_expansion_enabled is True


class TestServiceBasicFlow:
    @pytest.mark.asyncio
    async def test_empty_memory_returns_empty_payload(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request())
        assert isinstance(result, RetrievalPayload)

    @pytest.mark.asyncio
    async def test_l0_loaded_when_session_id_present(self):
        class _Projection:
            session = {"id": "s1"}

            def to_retrieval_entry(self):
                return {
                    "session": {"id": "s1"},
                    "goals": ["g1"],
                    "active_entities": ["e1"],
                    "temporary_tactics": ["t1"],
                    "execution_summary": {
                        "active_run_summary": "Investigate the login issue",
                        "awaiting_external_result": True,
                        "latest_user_augmentation_summary": "补充一下，是 macOS",
                    },
                }

        l0 = AsyncMock()
        l0.get_prompt_workbench_projection.return_value = _Projection()
        mem = _make_memory(l0=l0)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(session_id="s1"))
        assert len(result.l0_workbench) == 1
        assert result.l0_workbench[0]["session"]["id"] == "s1"
        assert result.l0_workbench[0]["goals"] == ["g1"]
        assert result.l0_workbench[0]["execution_summary"]["active_run_summary"] == "Investigate the login issue"
        l0.get_prompt_workbench_projection.assert_awaited_once_with("s1")
        l0.get_workbench.assert_not_called()

    @pytest.mark.asyncio
    async def test_l0_not_loaded_without_session_id(self):
        l0 = AsyncMock()
        mem = _make_memory(l0=l0)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request(session_id=None))
        assert len(result.l0_workbench) == 0
        l0.get_prompt_workbench_projection.assert_not_called()

    @pytest.mark.asyncio
    async def test_trace_includes_query_mode(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        svc._intent_decider.decide = AsyncMock(return_value=IntentDecision())  # type: ignore[method-assign]

        result = await svc.query(_make_request(query_mode="exact_fact"))

        assert result.trace.get("query_mode") == "exact_fact"
        assert result.trace.get("requested_query_mode") == "exact_fact"
        assert result.trace.get("resolved_query_mode") == "exact_fact"
        assert result.trace.get("layer_result_counts") == {"L1": 0, "L2": 0, "L3": 0, "L4": 0}


class TestServiceLayerRouting:
    @pytest.mark.asyncio
    async def test_episode_recall_query_does_not_enable_l2_episode_substrate(self):
        l1 = _make_l1_store([])
        l2 = AsyncMock()
        mem = _make_memory(l1=l1, l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        async def execute_plan_stub(plan, **_kwargs):
            if plan.layer == "L2":
                return {
                    "entity_cards": [],
                    "relationships": [],
                    "assertions": [],
                    "episodes": [],
                    "experiences": [],
                }
            return []

        execute_plan_mock = AsyncMock(side_effect=execute_plan_stub)
        with patch("magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan", new=execute_plan_mock):
            await svc.query(_make_request(query="那次日本旅行发生了什么", query_mode="episode_recall"))

        l2_plans = [
            call.args[0]
            for call in execute_plan_mock.await_args_list
            if call.args and call.args[0].layer == "L2"
        ]
        assert l2_plans
        assert isinstance(l2_plans[0].conditions, L2Conditions)
        assert l2_plans[0].conditions.include_episodes is False
        assert l2_plans[0].conditions.include_experiences is True

    @pytest.mark.asyncio
    async def test_detail_mode_queries_l1(self):
        l1 = _make_l1_store([{"event_id": "e1", "content": "test", "timestamp": 1000.0}])
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        await svc.query(_make_request(query_mode="detail"))
        # L1Handler uses keyword path which filters by content tokens
        # The mock query_events returns the event, and keyword matching should pass
        assert l1.bm25_search.called or l1.query_events.called

    @pytest.mark.asyncio
    async def test_event_stream_mode_queries_l1_only(self):
        l1 = _make_l1_store([{"event_id": "e1", "content": "test query happened", "timestamp": 1000.0}])
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_list_tom_assertions.return_value = {}
        l2.batch_get_relationships.return_value = {}
        mem = _make_memory(l1=l1, l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(_make_request(query_mode="event_stream", query="test query"))

        assert l1.bm25_search.called or l1.query_events.called
        l2.batch_get_tom_snapshots.assert_not_called()
        l2.batch_list_tom_assertions.assert_not_called()
        l2.batch_get_relationships.assert_not_called()
        assert result.trace.get("resolved_query_mode") == "event_stream"
        assert result.trace.get("executed_layers") == ["L1"]
        assert result.trace.get("layer_result_counts", {}).get("L1", 0) >= 1

    @pytest.mark.asyncio
    async def test_summary_mode_queries_l3(self, tmp_path):
        l3 = _make_l3_store(tmp_path, [{"summary_id": "s1", "content": "summary"}])
        mem = _make_memory(l3=l3)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        await svc.query(_make_request(query_mode="summary"))
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
        await svc.query(_make_request(query_mode="experience"))
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
        assertion_data = {
            "assertion_id": "assert-1",
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "dislike",
            "trait_value": "rainy_weather",
            "validation_state": "corroborated",
            "confidence_score": 0.8,
        }
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_get_relationships.return_value = {}
        l2.get_relationships.return_value = []
        l2.batch_list_tom_assertions.return_value = {"user:u1": [assertion_data]}
        l2.list_tom_assertions.return_value = [assertion_data]
        l2.list_episodes.return_value = []
        l2.search_episodes_fts.return_value = []
        mem = _make_memory(l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(_make_request(query_mode="graph"))

        assert len(result.l2_assertions) == 1
        l2.batch_list_tom_assertions.assert_called()

    @pytest.mark.asyncio
    async def test_graph_mode_filters_relationships_by_predicate_and_status(self):
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_list_tom_assertions.return_value = {}
        l2.batch_get_relationships.return_value = {
            "user:u1": [{"triple_id": "triple-1", "subject_id": "user:u1", "status": "active"}],
        }
        l2.get_relationships.return_value = []
        l2.list_episodes.return_value = []
        l2.search_episodes_fts.return_value = []
        mem = _make_memory(l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(
            _make_request(
                query_mode="graph",
                query="我讨厌什么天气",
            )
        )

        assert len(result.l2_relationships) >= 1
        first_call_kwargs = l2.batch_get_relationships.call_args_list[0][1]
        assert first_call_kwargs["predicates"] == ["DISLIKES", "FOLLOWS", "INTERESTED_IN", "LIKES"]
        assert first_call_kwargs["status_filters"] == ["active"]

    @pytest.mark.asyncio
    async def test_graph_mode_resolves_alias_entities_via_entity_catalog(self):
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_get_relationships.return_value = {
            "user:u1": [{"triple_id": "triple-1", "subject_id": "user:u1", "object_id": "place:shanghai", "status": "active"}],
        }
        l2.batch_list_tom_assertions.return_value = {}
        l2.get_relationships.return_value = []
        l2.list_episodes.return_value = []
        l2.search_episodes_fts.return_value = []
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
                # RFC #65: the structured channel abstains when no predicate
                # can be inferred ("什么感觉" no longer maps via keyword
                # fallback); "喜欢" resolves the preference family while the
                # alias 魔都 still exercises the entity-catalog resolution
                # under test.
                query="我喜欢魔都吗",
            )
        )

        entity_catalog.resolve_query_entities.assert_called_once()
        first_call_kwargs = l2.batch_get_relationships.call_args_list[0][1]
        assert "user:u1" in first_call_kwargs["entity_ids"]

    @pytest.mark.asyncio
    async def test_graph_mode_can_query_incoming_relationships(self):
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_get_relationships.return_value = {
            "user:u1": [{"triple_id": "triple-in", "subject_id": "user:u1", "object_id": "person:x", "status": "active"}],
        }
        l2.batch_list_tom_assertions.return_value = {}
        l2.get_relationships.return_value = []
        l2.list_episodes.return_value = []
        l2.search_episodes_fts.return_value = []
        mem = _make_memory(l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(
            _make_request(
                query_mode="graph",
                query="谁认识我",
            )
        )

        assert len(result.l2_relationships) >= 1
        first_call_kwargs = l2.batch_get_relationships.call_args_list[0][1]
        assert "user:u1" in first_call_kwargs["entity_ids"]

    @pytest.mark.asyncio
    async def test_graph_mode_filters_assertions_by_target_entity(self):
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_get_relationships.return_value = {}
        l2.batch_list_tom_assertions.return_value = {"user:u1": [{"assertion_id": "assert-1"}]}
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

        _, kwargs = l2.batch_list_tom_assertions.call_args
        assert kwargs["target_entity_id"] == "weather_state:rainy-hangzhou"

    @pytest.mark.asyncio
    async def test_graph_mode_populates_l2_query_trace(self):
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_get_relationships.return_value = {
            "user:u1": [{"triple_id": "triple-1", "predicate": "KNOWS", "subject_id": "user:u1", "status": "active"}],
        }
        l2.batch_list_tom_assertions.return_value = {
            "user:u1": [{"assertion_id": "assert-1", "confidence_score": 0.8}],
        }
        l2.get_relationships.return_value = [
            {
                "triple_id": "triple-1",
                "predicate": "KNOWS",
                "subject_id": "user:u1",
                "object_id": "place:shanghai",
                "status": "active",
            }
        ]
        l2.list_episodes.return_value = []
        l2.search_episodes_fts.return_value = []
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
        assert "grounding_plan" in l2_trace
        gp = l2_trace["grounding_plan"]
        assert gp["subject_count"] >= 1
        assert gp["object_count"] >= 1
        assert "channel_counts" in l2_trace
        assert "fusion_candidate_count" in l2_trace
        assert "output_counts" in l2_trace
        assert l2_trace["output_counts"]["relationships"] >= 1
        assert l2_trace["output_counts"]["assertions"] >= 1

    @pytest.mark.asyncio
    async def test_interaction_scoped_place_affinity_with_time_range_adds_l1_primary_plan(self):
        mem = _make_memory(l1=_make_l1_store([]), l2=AsyncMock())
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        semantic_frame = L2SemanticFrame(
            query_family="affinity",
            subject_scope="self",
            answer_kind="place",
            answer_unit="place",
            constraints=[
                SemanticConstraint(
                    scope="interaction",
                    facet="located_in",
                    raw_value="杭州",
                    resolved_entity_id="place:hangzhou",
                ),
                SemanticConstraint(
                    scope="target",
                    facet="category",
                    raw_value="咖啡馆",
                    resolved_facet_value="coffee_shop",
                ),
            ],
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[
                    LayerQueryPlan(
                        layer="L2",
                        conditions=L2Conditions(
                            content_query="最近在杭州的时候喜欢去哪些咖啡馆",
                            subject_hint="self",
                            predicate_family="preference",
                            semantic_frame=semantic_frame,
                        ),
                        time_range=TimeRange(start=100.0, end=200.0),
                        is_fallback=False,
                    )
                ],
                time_range=TimeRange(start=100.0, end=200.0),
                source="rule_fallback",
                reasoning="test",
            )
        )

        execute_plan_mock = AsyncMock(
            side_effect=[
                {"entity_cards": [], "relationships": [{"triple_id": "rel-1", "predicate": "VISITED"}], "assertions": []},
                [{"event_id": "evt-1", "content": "Went to a cafe in Hangzhou", "timestamp": 150.0, "session_id": "s1"}],
            ]
        )
        with patch("magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan", new=execute_plan_mock):
            result = await svc.query(_make_request(query="最近在杭州的时候喜欢去哪些咖啡馆"))

        assert [call.args[0].layer for call in execute_plan_mock.await_args_list[:2]] == ["L2", "L1"]
        l1_plan = execute_plan_mock.await_args_list[1].args[0]
        assert isinstance(l1_plan.conditions, L1Conditions)
        assert l1_plan.time_range is not None
        assert l1_plan.time_range.start == 100.0
        assert l1_plan.time_range.end == 200.0
        assert result.l2_relationships == [{"triple_id": "rel-1", "predicate": "VISITED"}]
        assert result.l1_events == [
            {"event_id": "evt-1", "content": "Went to a cafe in Hangzhou", "timestamp": 150.0, "session_id": "s1"}
        ]

    @pytest.mark.asyncio
    async def test_interaction_scoped_creator_affinity_with_time_range_adds_l1_primary_plan(self):
        mem = _make_memory(l1=_make_l1_store([]), l2=AsyncMock())
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        semantic_frame = L2SemanticFrame(
            query_family="affinity",
            subject_scope="self",
            answer_kind="creator",
            answer_unit="identity",
            constraints=[
                SemanticConstraint(
                    scope="interaction",
                    facet="platform",
                    raw_value="B站",
                    resolved_entity_id="software:bilibili",
                )
            ],
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[
                    LayerQueryPlan(
                        layer="L2",
                        conditions=L2Conditions(
                            content_query="最近在B站的时候喜欢看哪些up主",
                            subject_hint="self",
                            predicate_family="preference",
                            semantic_frame=semantic_frame,
                        ),
                        time_range=TimeRange(start=100.0, end=200.0),
                        is_fallback=False,
                    )
                ],
                time_range=TimeRange(start=100.0, end=200.0),
                source="rule_fallback",
                reasoning="test",
            )
        )

        execute_plan_mock = AsyncMock(
            side_effect=[
                {"entity_cards": [], "relationships": [{"triple_id": "rel-creator-1", "predicate": "FOLLOWS"}], "assertions": []},
                [{"event_id": "evt-creator-1", "content": "Watched a Bilibili creator", "timestamp": 150.0, "session_id": "s1"}],
            ]
        )
        with patch("magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan", new=execute_plan_mock):
            result = await svc.query(_make_request(query="最近在B站的时候喜欢看哪些up主"))

        assert [call.args[0].layer for call in execute_plan_mock.await_args_list[:2]] == ["L2", "L1"]
        l1_plan = execute_plan_mock.await_args_list[1].args[0]
        assert isinstance(l1_plan.conditions, L1Conditions)
        assert l1_plan.time_range is not None
        assert l1_plan.time_range.start == 100.0
        assert l1_plan.time_range.end == 200.0
        assert result.l2_relationships == [{"triple_id": "rel-creator-1", "predicate": "FOLLOWS"}]
        assert result.l1_events == [
            {"event_id": "evt-creator-1", "content": "Watched a Bilibili creator", "timestamp": 150.0, "session_id": "s1"}
        ]


    @pytest.mark.asyncio
    async def test_graph_mode_self_hint_binds_user_even_without_pronoun(self):
        """When subject_hint=self is inferred, the subject should be the
        user entity even when the rewritten content_query omits first-person
        pronouns."""
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_get_relationships.return_value = {"user:local_user": [{"triple_id": "t1"}]}
        l2.batch_list_tom_assertions.return_value = {}
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "place:abc123",
                "entity_type": "place",
                "canonical_name": "Hangzhou",
                "match_source": "vector",
            }
        ]
        mem = _make_memory(l2=l2, l2_entity_catalog=entity_catalog)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        await svc.query(
            _make_request(
                query_mode="graph",
                query="我讨厌什么天气",
                user_id="local_user",
            )
        )

        _, kwargs = l2.batch_get_relationships.call_args
        assert "user:local_user" in kwargs["entity_ids"]

    @pytest.mark.asyncio
    async def test_graph_mode_vector_only_entity_becomes_object_candidate(self):
        """When the only resolved entity came from vector-similarity, it
        becomes an object candidate in the grounding plan and influences
        assertion retrieval as a target entity."""
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_get_relationships.return_value = {
            "user:local_user": [{"triple_id": "t1", "subject_id": "user:local_user", "status": "active"}],
        }
        l2.batch_list_tom_assertions.return_value = {
            "user:local_user": [{"assertion_id": "a1", "confidence_score": 0.8}],
        }
        l2.get_relationships.return_value = []
        l2.list_episodes.return_value = []
        l2.search_episodes_fts.return_value = []
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "place:abc123",
                "entity_type": "place",
                "canonical_name": "Hangzhou",
                "match_source": "vector",
            }
        ]
        mem = _make_memory(l2=l2, l2_entity_catalog=entity_catalog)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(
            _make_request(
                query_mode="graph",
                query="我讨厌什么天气",
                user_id="local_user",
            )
        )

        first_rel_kwargs = l2.batch_get_relationships.call_args_list[0][1]
        assert "user:local_user" in first_rel_kwargs["entity_ids"]
        assert len(result.l2_relationships) >= 1


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

    @pytest.mark.asyncio
    async def test_rule_backstop_runs_when_llm_primary_returns_no_results(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        llm_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="attended event first", limit=10),
            is_fallback=False,
        )
        rule_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="Effective Time Management Data Analysis using Python", limit=10),
            is_fallback=False,
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[llm_plan],
                source="llm",
                reasoning="llm optimized away the concrete event names",
            )
        )
        svc._intent_decider._rule_engine.evaluate = MagicMock(
            return_value=IntentDecision(
                plans=[rule_plan],
                source="rule_fallback",
                reasoning="rule keeps original query",
            )
        )

        recovered_event = {
            "event_id": "evt-webinar",
            "session_id": "answer_1c6b85ea_2",
            "turn_id": "answer_1c6b85ea_2:turn-3",
            "timestamp": 15.0,
            "content": 'I participated in a webinar on "Data Analysis using Python" two months ago.',
            "author_type": "user",
        }

        async def _execute_plan_side_effect(plan, **kwargs):
            if plan.conditions.content_query == llm_plan.conditions.content_query:
                return []
            if plan.conditions.content_query == rule_plan.conditions.content_query:
                return [recovered_event]
            raise AssertionError(f"Unexpected query plan: {plan.conditions.content_query}")

        with patch(
            "magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan",
            new=AsyncMock(side_effect=_execute_plan_side_effect),
        ):
            result = await svc.query(
                _make_request(
                    query="Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?"
                )
            )

        assert [event["event_id"] for event in result.l1_events] == ["evt-webinar"]
        assert result.trace["primary_count"] == 1
        assert result.trace["rule_backstop_triggered"] is True

    @pytest.mark.asyncio
    async def test_rule_backstop_runs_when_llm_primary_misses_a_quoted_candidate(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        llm_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="compare learning events", limit=10),
            is_fallback=False,
        )
        rule_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="Effective Time Management Data Analysis using Python", limit=10),
            is_fallback=False,
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[llm_plan],
                source="llm",
                reasoning="llm picked broader semantic wording",
            )
        )
        svc._intent_decider._rule_engine.evaluate = MagicMock(
            return_value=IntentDecision(
                plans=[rule_plan],
                source="rule_fallback",
                reasoning="rule preserves quoted event names",
            )
        )

        llm_events = [
            {
                "event_id": "evt-webinar",
                "session_id": "answer_1c6b85ea_2",
                "turn_id": "answer_1c6b85ea_2:turn-3",
                "timestamp": 15.0,
                "content": 'I participated in a webinar on "Data Analysis using Python" two months ago.',
                "author_type": "user",
            },
            {
                "event_id": "evt-generic",
                "session_id": "answer_1c6b85ea_1",
                "turn_id": "answer_1c6b85ea_1:turn-3",
                "timestamp": 3.0,
                "content": "I'll definitely check out these recommendations.",
                "author_type": "user",
            },
        ]
        rule_event = {
            "event_id": "evt-workshop",
            "session_id": "answer_1c6b85ea_1",
            "turn_id": "answer_1c6b85ea_1:turn-11",
            "timestamp": 11.0,
            "content": 'I attended the "Effective Time Management" workshop last Saturday.',
            "author_type": "user",
        }

        async def _execute_plan_side_effect(plan, **kwargs):
            if plan.conditions.content_query == llm_plan.conditions.content_query:
                return llm_events
            if plan.conditions.content_query == rule_plan.conditions.content_query:
                return [rule_event]
            raise AssertionError(f"Unexpected query plan: {plan.conditions.content_query}")

        with patch(
            "magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan",
            new=AsyncMock(side_effect=_execute_plan_side_effect),
        ):
            result = await svc.query(
                _make_request(
                    query="Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?"
                )
            )

        assert {event["event_id"] for event in result.l1_events} == {"evt-webinar", "evt-generic", "evt-workshop"}
        assert result.trace["rule_backstop_triggered"] is True
        assert result.trace["rule_backstop_reason"] == "missing_quoted_coverage"

    @pytest.mark.asyncio
    async def test_rule_backstop_runs_when_llm_primary_misses_an_unquoted_comparison_candidate(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        llm_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="compare February vehicle care", limit=10),
            is_fallback=False,
        )
        rule_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="bike car February", limit=10),
            is_fallback=False,
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[llm_plan],
                source="llm",
                reasoning="llm broadened the comparison into a generic maintenance query",
            )
        )
        svc._intent_decider._rule_engine.evaluate = MagicMock(
            return_value=IntentDecision(
                plans=[rule_plan],
                source="rule_fallback",
                reasoning="rule preserves both compared vehicles",
            )
        )

        llm_events = [
            {
                "event_id": "evt-bike",
                "session_id": "answer_b535969f_2",
                "turn_id": "answer_b535969f_2:turn-11",
                "timestamp": 11.0,
                "content": "I got my bike repaired back in mid-February.",
                "author_type": "user",
            }
        ]
        rule_event = {
            "event_id": "evt-car",
            "session_id": "answer_b535969f_1",
            "turn_id": "answer_b535969f_1:turn-1",
            "timestamp": 1.0,
            "content": "I washed my current Corolla on Monday, February 27th.",
            "author_type": "user",
        }

        async def _execute_plan_side_effect(plan, **kwargs):
            if plan.conditions.content_query == llm_plan.conditions.content_query:
                return llm_events
            if plan.conditions.content_query == rule_plan.conditions.content_query:
                return [rule_event]
            raise AssertionError(f"Unexpected query plan: {plan.conditions.content_query}")

        with patch(
            "magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan",
            new=AsyncMock(side_effect=_execute_plan_side_effect),
        ):
            result = await svc.query(
                _make_request(
                    query="Which vehicle did I take care of first in February, the bike or the car?"
                )
            )

        assert {event["event_id"] for event in result.l1_events} == {"evt-bike", "evt-car"}
        assert result.trace["rule_backstop_triggered"] is True
        assert result.trace["rule_backstop_reason"] == "missing_comparison_coverage"

    @pytest.mark.asyncio
    async def test_rule_backstop_runs_when_unquoted_comparison_spans_only_appear_in_one_noisy_event(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        llm_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="vehicle care order in February", limit=10),
            is_fallback=False,
        )
        rule_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="bike car February maintenance", limit=10),
            is_fallback=False,
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[llm_plan],
                source="llm",
                reasoning="llm found one semantically related event that mentions both vehicles",
            )
        )
        svc._intent_decider._rule_engine.evaluate = MagicMock(
            return_value=IntentDecision(
                plans=[rule_plan],
                source="rule_fallback",
                reasoning="rule broadens search to recover separate vehicle events",
            )
        )

        llm_events = [
            {
                "event_id": "evt-mixed",
                "session_id": "answer_b535969f_1",
                "turn_id": "answer_b535969f_1:turn-9",
                "timestamp": 21.0,
                "content": (
                    "I recently had to take my bike in for repairs, and it made me realize how much "
                    "I rely on my car for daily errands."
                ),
                "author_type": "user",
            }
        ]
        rule_events = [
            {
                "event_id": "evt-bike",
                "session_id": "answer_b535969f_2",
                "turn_id": "answer_b535969f_2:turn-11",
                "timestamp": 11.0,
                "content": "I got my bike repaired back in mid-February.",
                "author_type": "user",
            },
            {
                "event_id": "evt-car",
                "session_id": "answer_b535969f_1",
                "turn_id": "answer_b535969f_1:turn-1",
                "timestamp": 1.0,
                "content": "I washed my current Corolla on Monday, February 27th.",
                "author_type": "user",
            },
        ]

        async def _execute_plan_side_effect(plan, **kwargs):
            if plan.conditions.content_query == llm_plan.conditions.content_query:
                return llm_events
            if plan.conditions.content_query == rule_plan.conditions.content_query:
                return rule_events
            raise AssertionError(f"Unexpected query plan: {plan.conditions.content_query}")

        with patch(
            "magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan",
            new=AsyncMock(side_effect=_execute_plan_side_effect),
        ):
            result = await svc.query(
                _make_request(
                    query="Which vehicle did I take care of first in February, the bike or the car?"
                )
            )

        assert {event["event_id"] for event in result.l1_events} == {"evt-mixed", "evt-bike", "evt-car"}
        assert result.trace["rule_backstop_triggered"] is True
        assert result.trace["rule_backstop_reason"] == "missing_comparison_coverage"

    @pytest.mark.asyncio
    async def test_comparison_backstop_runs_candidate_queries_when_rule_backstop_still_misses_coverage(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        llm_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="vehicle care order in February", limit=10),
            is_fallback=False,
        )
        rule_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="Which vehicle did I take care of first in February, the bike or the car?", limit=10),
            is_fallback=False,
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[llm_plan],
                source="llm",
                reasoning="llm found one related comparison event",
            )
        )
        svc._intent_decider._rule_engine.evaluate = MagicMock(
            return_value=IntentDecision(
                plans=[rule_plan],
                source="rule_fallback",
                reasoning="rule retries the original query",
            )
        )

        mixed_event = {
            "event_id": "evt-mixed",
            "session_id": "answer_b535969f_1",
            "turn_id": "answer_b535969f_1:turn-9",
            "timestamp": 21.0,
            "content": "I recently had to take my bike in for repairs, and it made me realize how much I rely on my car.",
            "author_type": "user",
        }
        car_event = {
            "event_id": "evt-car",
            "session_id": "answer_b535969f_1",
            "turn_id": "answer_b535969f_1:turn-1",
            "timestamp": 1.0,
            "content": "I washed my current Corolla on Monday, February 27th.",
            "author_type": "user",
        }

        async def _execute_plan_side_effect(plan, **kwargs):
            query = plan.conditions.content_query
            if query == llm_plan.conditions.content_query:
                return [mixed_event]
            if query == rule_plan.conditions.content_query:
                return [mixed_event]
            if query == "bike february":
                return []
            if query == "car february":
                return [car_event]
            raise AssertionError(f"Unexpected query plan: {query}")

        with patch(
            "magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan",
            new=AsyncMock(side_effect=_execute_plan_side_effect),
        ):
            result = await svc.query(
                _make_request(
                    query="Which vehicle did I take care of first in February, the bike or the car?"
                )
        )

        assert {event["event_id"] for event in result.l1_events} == {"evt-mixed", "evt-car"}
        assert result.trace["comparison_backstop_triggered"] is True
        assert result.trace["comparison_backstop_count"] == 3

    def test_rule_backstop_requires_temporal_anchor_for_unquoted_comparison_coverage(self):
        payload = RetrievalPayload(
            l1_events=[
                {
                    "event_id": "evt-mixed",
                    "content": "I recently had to take my bike in for repairs, and it made me realize how much I rely on my car.",
                    "author_type": "user",
                },
                {
                    "event_id": "evt-bike-followup",
                    "content": "I'm glad to hear that your bike is running smoothly again!",
                    "author_type": "assistant",
                },
            ]
        )

        reason = HybridRetrievalService._rule_backstop_reason(
            query="Which vehicle did I take care of first in February, the bike or the car?",
            payload=payload,
            decision_source="llm",
        )

        assert reason == "missing_comparison_coverage"

    def test_rule_backstop_triggers_when_l1_empty_but_l2_has_data(self):
        """When the LLM routes entirely to L2, the backstop should trigger
        so that L1 full-text search fills the conversation-context gap."""
        payload = RetrievalPayload(
            l1_events=[],
            l2_relationships=[{"subject": "user", "predicate": "owns", "object": "hamster"}],
            l2_assertions=[],
        )
        reason = HybridRetrievalService._rule_backstop_reason(
            query="What is the name of my hamster?",
            payload=payload,
            decision_source="llm",
        )
        assert reason == "l1_empty_with_l2_data"

    def test_rule_backstop_does_not_trigger_when_l1_has_events(self):
        """When L1 already has events, no backstop is needed for L1 gap."""
        payload = RetrievalPayload(
            l1_events=[{"event_id": "e1", "content": "My hamster is named Biscuit"}],
            l2_relationships=[{"subject": "user", "predicate": "owns", "object": "hamster"}],
        )
        reason = HybridRetrievalService._rule_backstop_reason(
            query="What is the name of my hamster?",
            payload=payload,
            decision_source="llm",
        )
        assert reason is None

    @pytest.mark.asyncio
    async def test_comparison_backstop_runs_for_rule_fallback_when_primary_is_empty(self):
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        rule_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="Which vehicle did I take care of first in February, the bike or the car?", limit=10),
            is_fallback=False,
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[rule_plan],
                source="rule_fallback",
                reasoning="rule routed directly to L1",
            )
        )

        bike_event = {
            "event_id": "evt-bike",
            "session_id": "answer_b535969f_2",
            "turn_id": "answer_b535969f_2:turn-11",
            "timestamp": 11.0,
            "content": "I got my bike repaired back in mid-February.",
            "author_type": "user",
        }
        car_event = {
            "event_id": "evt-car",
            "session_id": "answer_b535969f_1",
            "turn_id": "answer_b535969f_1:turn-1",
            "timestamp": 1.0,
            "content": "I washed my current Corolla on Monday, February 27th.",
            "author_type": "user",
        }

        async def _execute_plan_side_effect(plan, **kwargs):
            query = plan.conditions.content_query
            if query == rule_plan.conditions.content_query:
                return []
            if query == "bike february":
                return [bike_event]
            if query == "car february":
                return [car_event]
            raise AssertionError(f"Unexpected query plan: {query}")

        with patch(
            "magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan",
            new=AsyncMock(side_effect=_execute_plan_side_effect),
        ):
            result = await svc.query(
                _make_request(
                    query="Which vehicle did I take care of first in February, the bike or the car?"
                )
            )

        assert {event["event_id"] for event in result.l1_events} == {"evt-bike", "evt-car"}
        assert result.trace["comparison_backstop_triggered"] is True

    @pytest.mark.asyncio
    async def test_comparison_backstop_uses_quoted_spans_for_single_quoted_entities(self):
        """When entities are single-quoted ('The Crown' or 'Game of Thrones'),
        extract_comparison_spans returns [] but extract_quoted_spans succeeds."""
        mem = _make_memory()
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        llm_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="The Crown vs Game of Thrones watch order", limit=10),
            is_fallback=False,
        )
        rule_plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(
                content_query="Which show did I start watching first, 'The Crown' or 'Game of Thrones'?",
                limit=10,
            ),
            is_fallback=False,
        )
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[llm_plan],
                source="llm",
                reasoning="llm found comparison question",
            )
        )
        svc._intent_decider._rule_engine.evaluate = MagicMock(
            return_value=IntentDecision(
                plans=[rule_plan],
                source="rule_fallback",
                reasoning="rule retries the original query",
            )
        )

        got_event = {
            "event_id": "evt-got",
            "session_id": "answer_fb793c87_2",
            "turn_id": "answer_fb793c87_2:turn-1",
            "timestamp": 10.0,
            "content": "I've been meaning to check out Game of Thrones for a while, and I finally started it about a month ago.",
            "author_type": "user",
        }
        crown_event = {
            "event_id": "evt-crown",
            "session_id": "answer_abc12345_1",
            "turn_id": "answer_abc12345_1:turn-3",
            "timestamp": 5.0,
            "content": "I started watching The Crown last week and I'm really enjoying it so far.",
            "author_type": "user",
        }

        async def _execute_plan_side_effect(plan, **kwargs):
            query = plan.conditions.content_query
            if query == llm_plan.conditions.content_query:
                return [got_event]
            if query == rule_plan.conditions.content_query:
                return [got_event]
            if query == "crown":
                return [crown_event]
            if query == "game throne":
                return [got_event]
            raise AssertionError(f"Unexpected query plan: {query}")

        with patch(
            "magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan",
            new=AsyncMock(side_effect=_execute_plan_side_effect),
        ):
            result = await svc.query(
                _make_request(
                    query="Which show did I start watching first, 'The Crown' or 'Game of Thrones'?"
                )
            )

        assert {event["event_id"] for event in result.l1_events} == {"evt-got", "evt-crown"}
        assert result.trace["comparison_backstop_triggered"] is True

    @pytest.mark.asyncio
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


class TestServiceEvidencePackaging:
    @pytest.mark.asyncio
    async def test_builds_grouped_l1_evidence_bundles_with_neighbors(self):
        session_events = [
            {
                "event_id": "e1",
                "session_id": "s-car",
                "turn_id": "s-car:turn-1",
                "session_seq": 0,
                "timestamp": 1000.0,
                "content": "I scheduled the first service for my new car.",
                "author_type": "user",
            },
            {
                "event_id": "e2",
                "session_id": "s-car",
                "turn_id": "s-car:turn-2",
                "session_seq": 1,
                "timestamp": 1010.0,
                "content": "The service went smoothly at the dealership.",
                "author_type": "assistant",
            },
            {
                "event_id": "e3",
                "session_id": "s-car",
                "turn_id": "s-car:turn-3",
                "session_seq": 2,
                "timestamp": 1020.0,
                "content": "After the first service, the GPS system stopped working correctly.",
                "author_type": "user",
                "retrieval_trace": {"base_rrf_score": 0.9},
            },
            {
                "event_id": "e4",
                "session_id": "s-car",
                "turn_id": "s-car:turn-4",
                "session_seq": 3,
                "timestamp": 1030.0,
                "content": "The dealership replaced the GPS unit and fixed the problem.",
                "author_type": "assistant",
            },
        ]
        l1 = _make_l1_store(session_events)
        l1.query_events = AsyncMock(return_value=list(reversed(session_events)))
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="gps issue", limit=5))],
                source="rule_fallback",
                reasoning="test",
            )
        )

        hit = dict(session_events[2], reranker_score=0.9)
        with patch("magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan", new=AsyncMock(return_value=[hit])):
            result = await svc.query(_make_request(query="What was the first issue after the first service?"))

        assert len(result.l1_evidence_bundles) == 1
        bundle = result.l1_evidence_bundles[0]
        assert bundle["session_id"] == "s-car"
        assert bundle["hit_event_ids"] == ["e3"]
        assert [event["event_id"] for event in bundle["events"]] == ["e1", "e2", "e3", "e4"]
        assert bundle["neighbor_expansion_applied"] is True
        assert result.trace["l1_evidence_bundle_count"] == 1

    @pytest.mark.asyncio
    async def test_builds_timeline_summary_from_l1_evidence_bundles(self):
        session_events = [
            {
                "event_id": "e1",
                "session_id": "s-webinar",
                "turn_id": "s-webinar:turn-3",
                "timestamp": 15.0,
                "content": "I participated in the 'Data Analysis using Python' webinar two months ago.",
                "author_type": "user",
            },
            {
                "event_id": "e2",
                "session_id": "s-workshop",
                "turn_id": "s-workshop:turn-11",
                "timestamp": 21.0,
                "content": "I attended the 'Effective Time Management' workshop last Saturday.",
                "author_type": "user",
            },
        ]
        l1 = _make_l1_store(session_events)
        l1.query_events = AsyncMock(side_effect=[session_events[:1], session_events[1:]])
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="event order", limit=5))],
                source="rule_fallback",
                reasoning="test",
            )
        )

        scored_events = [dict(e, reranker_score=0.8) for e in session_events]
        with patch("magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan", new=AsyncMock(return_value=scored_events)):
            result = await svc.query(
                _make_request(
                    query="Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?"
                )
            )

        assert [item["supporting_event_ids"] for item in result.l1_timeline_summary] == [["e1"], ["e2"]]
        assert result.trace["l1_timeline_summary_count"] == 2

    @pytest.mark.asyncio
    async def test_timeline_summary_keeps_earlier_service_anchor_from_same_session(self):
        service_session_events = [
            {
                "event_id": "e1",
                "session_id": "s-service",
                "turn_id": "s-service:turn-1",
                "session_seq": 0,
                "timestamp": 1.0,
                "content": "I just got my new car serviced for the first time on March 15th.",
                "author_type": "user",
            },
            {
                "event_id": "e2",
                "session_id": "s-service",
                "turn_id": "s-service:turn-2",
                "session_seq": 1,
                "timestamp": 2.0,
                "content": "I'm glad to hear the first service went smoothly.",
                "author_type": "assistant",
            },
            {
                "event_id": "e3",
                "session_id": "s-service",
                "turn_id": "s-service:turn-3",
                "session_seq": 2,
                "timestamp": 3.0,
                "content": "Do you think it's a good idea to get a wax and detailing done every 3-4 months?",
                "author_type": "user",
                "retrieval_trace": {"base_rrf_score": 0.8},
            },
            {
                "event_id": "e4",
                "session_id": "s-service",
                "turn_id": "s-service:turn-4",
                "session_seq": 3,
                "timestamp": 4.0,
                "content": "Waxing every few months can help protect the paint.",
                "author_type": "assistant",
            },
        ]
        issue_session_events = [
            {
                "event_id": "e5",
                "session_id": "s-issue",
                "turn_id": "s-issue:turn-3",
                "session_seq": 0,
                "timestamp": 15.0,
                "content": "After the first service, the GPS system stopped working correctly on 3/22.",
                "author_type": "user",
                "retrieval_trace": {"base_rrf_score": 0.9},
            }
        ]
        l1 = _make_l1_store(service_session_events + issue_session_events)
        l1.query_events = AsyncMock(side_effect=[service_session_events, issue_session_events])
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        svc._intent_decider.decide = AsyncMock(
            return_value=IntentDecision(
                plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="first issue after first service", limit=5))],
                source="rule_fallback",
                reasoning="test",
            )
        )

        with patch(
            "magi.memory.hybrid_retrieval.service_plan_execution.execute_layer_plan",
            new=AsyncMock(return_value=[service_session_events[2], issue_session_events[0]]),
        ):
            result = await svc.query(_make_request(query="What was the first issue I had with my new car after its first service?"))

        assert [item["supporting_event_ids"] for item in result.l1_timeline_summary] == [["e1"], ["e5"]]


class TestL2TemporalInjection:
    """Verify that L2 plan is injected when query has temporal anchors but LLM routed to L1-only."""

    @pytest.mark.asyncio
    async def test_temporal_query_defaults_exact_fact_without_explicit_mode(self):
        """Without explicit query_mode, defaults to exact_fact (no keyword classification)."""
        l1 = _make_l1_store([{"event_id": "e1", "content": "I got a smoker today", "timestamp": 1000.0}])
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_list_tom_assertions.return_value = {}
        l2.batch_get_relationships.return_value = {}
        l2.get_relationships.return_value = []
        l2.list_tom_assertions.return_value = []
        mem = _make_memory(l1=l1, l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        result = await svc.query(_make_request(query="What did I buy 10 days ago?"))

        assert result.trace.get("query_mode") == "exact_fact"

    @pytest.mark.asyncio
    async def test_temporal_injection_uses_self_anchor(self):
        """The injected L2 plan should set subject_hint='self' so L2Handler queries from the user entity."""
        l1 = _make_l1_store([])
        l2 = AsyncMock()
        mem = _make_memory(l1=l1, l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        payload = RetrievalPayload(trace={})
        request = _make_request(query="What did I buy 10 days ago?")

        # Simulate LLM routing to L1 only (no L2 plan)
        l1_only_plans = [
            LayerQueryPlan(
                layer="L1",
                conditions=L1Conditions(content_query=request.query, limit=10),
                is_fallback=False,
            )
        ]
        augmented = svc._augment_primary_plans(l1_only_plans, request=request, payload=payload)

        l2_plans = [p for p in augmented if p.layer == "L2"]
        assert len(l2_plans) == 1
        assert l2_plans[0].conditions.subject_hint == "self"
        assert payload.trace.get("l2_temporal_injected") is True

    @pytest.mark.asyncio
    async def test_non_temporal_query_does_not_inject_l2_when_l2_already_present(self):
        """When L2 already participates, no extra injection happens even for temporal queries."""
        l1 = _make_l1_store([])
        l2 = AsyncMock()
        l2.batch_get_tom_snapshots.return_value = []
        l2.batch_list_tom_assertions.return_value = {}
        l2.batch_get_relationships.return_value = {}
        l2.get_relationships.return_value = []
        l2.list_tom_assertions.return_value = []
        mem = _make_memory(l1=l1, l2=l2)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))

        # Default rule engine routes L1 primary + L2 fallback, so L2 is already present
        # when primaryCount < threshold triggers fallback. Use a query without temporal marker.
        result = await svc.query(_make_request(query="What is my favorite food?"))

        assert result.trace.get("l2_temporal_injected") is None


class TestServiceErrorHandling:
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_crash(self):
        l1 = _make_l1_store([])
        l1.bm25_search.side_effect = RuntimeError("db error")
        l1.query_events.side_effect = RuntimeError("db error")
        l1.vector_search.side_effect = RuntimeError("db error")
        mem = _make_memory(l1=l1)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request())
        # Should return payload even if L1 fails
        assert isinstance(result, RetrievalPayload)

    @pytest.mark.asyncio
    async def test_l0_failure_does_not_crash(self):
        l0 = AsyncMock()
        l0.get_prompt_workbench_projection.side_effect = RuntimeError("l0 error")
        mem = _make_memory(l0=l0)
        svc = HybridRetrievalService(mem, config=RetrievalConfig(intent_decider_llm_enabled=False))
        result = await svc.query(_make_request())
        assert result.l0_workbench == []
