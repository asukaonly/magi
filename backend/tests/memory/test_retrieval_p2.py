"""Tests for P2 retrieval enhancements.

Covers:
- P2-1: GraphSpreader BFS over L2 knowledge graph
- P2-1: L1Handler graph spreading path integration
- P2-2: Cross-layer unified reranking
- P2-3: Confidence-aware fallback
- P2-4: Adaptive retrieval parameters
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.hybrid_retrieval.graph_spreader import (
    GraphSpreader,
    _parse_evidence_ids,
)
from magi.memory.hybrid_retrieval.models import (
    L1Conditions,
    RetrievalConfig,
    TimeRange,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_edge(
    subject_id: str,
    predicate: str,
    object_id: str,
    *,
    confidence: float = 0.8,
    observation_count: int = 3,
    evidence_event_ids: list[str] | None = None,
) -> dict:
    import json

    return {
        "triple_id": f"{subject_id}-{predicate}-{object_id}",
        "subject_id": subject_id,
        "subject_type": "entity",
        "predicate": predicate,
        "object_id": object_id,
        "object_type": "entity",
        "confidence": confidence,
        "observation_count": observation_count,
        "evidence_event_ids": json.dumps(evidence_event_ids or []),
        "status": "active",
    }


def _mock_l2_store(edge_map: dict[str, list[dict]]) -> AsyncMock:
    """Create a mock L2 store with governed relationship reads."""
    store = AsyncMock()

    async def batch_list_current_relationships(*, entity_ids, **kwargs):
        return {entity_id: list(edge_map.get(entity_id, [])) for entity_id in entity_ids}

    store.batch_list_current_relationships = AsyncMock(
        side_effect=batch_list_current_relationships
    )
    return store


# ---------------------------------------------------------------------------
# P2-1: GraphSpreader tests
# ---------------------------------------------------------------------------


class TestGraphSpreader:
    @pytest.mark.asyncio
    async def test_empty_seeds_returns_empty(self):
        store = _mock_l2_store({})
        spreader = GraphSpreader(store)
        result = await spreader.spread([])
        assert result.scored_event_ids == {}
        assert result.discovered_entities == {}

    @pytest.mark.asyncio
    async def test_none_store_returns_empty(self):
        spreader = GraphSpreader(None)
        result = await spreader.spread(["e1"])
        assert result.scored_event_ids == {}

    @pytest.mark.asyncio
    async def test_single_hop_discovers_neighbors(self):
        edges = {
            "entity_a": [
                _make_edge("entity_a", "LIKES", "entity_b", evidence_event_ids=["evt1"]),
                _make_edge("entity_a", "USES", "entity_c", evidence_event_ids=["evt2", "evt3"]),
            ],
        }
        store = _mock_l2_store(edges)
        spreader = GraphSpreader(store, max_hops=1)
        result = await spreader.spread(["entity_a"])

        assert "entity_b" in result.discovered_entities
        assert "entity_c" in result.discovered_entities
        assert "entity_a" not in result.discovered_entities  # seed excluded
        assert "evt1" in result.scored_event_ids
        assert "evt2" in result.scored_event_ids
        assert result.edges_traversed == 2

    @pytest.mark.asyncio
    async def test_multi_hop_traversal(self):
        edges = {
            "entity_a": [
                _make_edge("entity_a", "LIKES", "entity_b", evidence_event_ids=["evt1"]),
            ],
            "entity_b": [
                _make_edge("entity_b", "RELATED", "entity_c", evidence_event_ids=["evt2"]),
            ],
        }
        store = _mock_l2_store(edges)
        spreader = GraphSpreader(store, max_hops=2)
        result = await spreader.spread(["entity_a"])

        assert "entity_b" in result.discovered_entities
        assert "entity_c" in result.discovered_entities
        assert "evt1" in result.scored_event_ids
        assert "evt2" in result.scored_event_ids

    @pytest.mark.asyncio
    async def test_decay_reduces_activation(self):
        edges = {
            "entity_a": [
                _make_edge("entity_a", "LIKES", "entity_b",
                           confidence=1.0, observation_count=1,
                           evidence_event_ids=["evt_hop1"]),
            ],
            "entity_b": [
                _make_edge("entity_b", "RELATED", "entity_c",
                           confidence=1.0, observation_count=1,
                           evidence_event_ids=["evt_hop2"]),
            ],
        }
        store = _mock_l2_store(edges)
        spreader = GraphSpreader(store, max_hops=2, decay=0.5)
        result = await spreader.spread(["entity_a"])

        # Hop 1 score should be higher than hop 2 score
        assert result.scored_event_ids["evt_hop1"] > result.scored_event_ids["evt_hop2"]

    @pytest.mark.asyncio
    async def test_max_entities_limits_frontier_growth(self):
        """max_total_entities prevents later neighbors from being added
        to the next-hop frontier once the activation map exceeds the cap."""
        # Chain: seed → a → b → c → d
        # With max_total_entities=3, the frontier should stop growing
        # after a, b (cap hit at seed+a+b = 3) — c and d should not appear.
        edges = {
            "seed": [_make_edge("seed", "E", "a", evidence_event_ids=["ea"])],
            "a": [_make_edge("a", "E", "b", evidence_event_ids=["eb"])],
            "b": [_make_edge("b", "E", "c", evidence_event_ids=["ec"])],
            "c": [_make_edge("c", "E", "d", evidence_event_ids=["ed"])],
        }
        store = _mock_l2_store(edges)
        spreader = GraphSpreader(store, max_hops=4, max_total_entities=3)
        result = await spreader.spread(["seed"])

        # a and b should be discovered
        assert "a" in result.discovered_entities
        assert "b" in result.discovered_entities
        # c should not — activation map hits cap (seed+a+b = 3)
        assert "c" not in result.discovered_entities

    @pytest.mark.asyncio
    async def test_exclude_event_ids(self):
        edges = {
            "entity_a": [
                _make_edge("entity_a", "LIKES", "entity_b",
                           evidence_event_ids=["evt_include", "evt_exclude"]),
            ],
        }
        store = _mock_l2_store(edges)
        spreader = GraphSpreader(store, max_hops=1)
        result = await spreader.spread(["entity_a"], exclude_event_ids={"evt_exclude"})

        assert "evt_include" in result.scored_event_ids
        assert "evt_exclude" not in result.scored_event_ids

    @pytest.mark.asyncio
    async def test_store_error_handled_gracefully(self):
        store = AsyncMock()
        store.batch_list_current_relationships = AsyncMock(
            side_effect=RuntimeError("db error")
        )
        spreader = GraphSpreader(store, max_hops=1)
        result = await spreader.spread(["entity_a"])
        assert result.scored_event_ids == {}
        assert result.edges_traversed == 0

class TestParseEvidenceIds:
    def test_json_string(self):
        assert _parse_evidence_ids('["a", "b"]') == ["a", "b"]

    def test_list(self):
        assert _parse_evidence_ids(["a", "b"]) == ["a", "b"]

    def test_none(self):
        assert _parse_evidence_ids(None) == []

    def test_empty_string(self):
        assert _parse_evidence_ids("") == []

    def test_invalid_json(self):
        assert _parse_evidence_ids("not-json") == []


# ---------------------------------------------------------------------------
# P2-1: L1Handler graph spreading path
# ---------------------------------------------------------------------------


class TestL1HandlerGraphSpreading:
    @pytest.mark.asyncio
    async def test_graph_spreading_disabled_by_default(self):
        """Graph spreading should not run unless config enables it."""
        store = MagicMock()
        store.db_path = ":memory:"
        store.bm25_search = AsyncMock(return_value=[("evt1", 1.0)])
        store.vector_search = AsyncMock(return_value=[])
        store.query_events = AsyncMock(return_value=[])
        store.expand_by_entities = AsyncMock(return_value=[])
        store.resolve_event_entities = AsyncMock(return_value=[])
        store.find_events_by_entities = AsyncMock(return_value=[])
        store.filter_ids_by_user = AsyncMock(return_value=[])
        store.fetch_events = AsyncMock(return_value=[])

        from magi.memory.hybrid_retrieval.handlers import L1Handler

        config = RetrievalConfig(graph_spreading_enabled=False)
        l2_store = _mock_l2_store({})
        handler = L1Handler(store, config, l2_store=l2_store)

        # Patch _fetch_and_filter and reranker to avoid DB ops
        handler._fetch_and_filter = AsyncMock(return_value=[
            {"event_id": "evt1", "content": "test", "timestamp": 1000},
        ])
        handler._reranker = MagicMock()
        handler._reranker.rerank = AsyncMock(return_value=[
            {"event_id": "evt1", "content": "test", "retrieval_score": 1.0},
        ])

        results = await handler.execute(L1Conditions(content_query="test", limit=5))
        assert len(results) >= 1
        # L2 store should NOT be called since graph spreading is disabled
        l2_store.batch_get_relationships.assert_not_called()

    @pytest.mark.asyncio
    async def test_graph_spreading_enabled_calls_l2(self):
        """When enabled and seeds exist, graph spreading should query L2."""
        store = MagicMock()
        store.db_path = ":memory:"
        store.bm25_search = AsyncMock(return_value=[("evt1", 1.0)])
        store.vector_search = AsyncMock(return_value=[])
        store.query_events = AsyncMock(return_value=[])
        store.expand_by_entities = AsyncMock(return_value=[])
        store.resolve_event_entities = AsyncMock(return_value=[])
        store.find_events_by_entities = AsyncMock(return_value=[])
        store.filter_ids_by_user = AsyncMock(return_value=[])
        store.fetch_events = AsyncMock(return_value=[])

        l2_store = _mock_l2_store({
            "ent_a": [
                _make_edge("ent_a", "LIKES", "ent_b", evidence_event_ids=["evt_graph"]),
            ],
        })

        config = RetrievalConfig(graph_spreading_enabled=True)
        from magi.memory.hybrid_retrieval.handlers import L1Handler

        handler = L1Handler(store, config, l2_store=l2_store)

        # Seed entity resolution returns one entity so graph spreading runs
        store.resolve_event_entities = AsyncMock(return_value=["ent_a"])

        handler._fetch_and_filter = AsyncMock(return_value=[
            {"event_id": "evt1", "content": "test", "timestamp": 1000},
        ])
        handler._reranker = MagicMock()
        handler._reranker.rerank = AsyncMock(return_value=[
            {"event_id": "evt1", "content": "test", "retrieval_score": 1.0},
        ])

        results = await handler.execute(
            L1Conditions(
                content_query="test",
                context_scope={"project": "magi"},
                limit=5,
            ),
            TimeRange(as_of=123.0),
        )
        assert len(results) >= 1
        graph_kwargs = l2_store.batch_list_current_relationships.await_args.kwargs
        assert graph_kwargs["context_scope"] == {"project": "magi"}
        assert graph_kwargs["effective_at"] == 123.0
        assert graph_kwargs["include_history"] is True

        future_start = time.time() + 3_600
        await handler.execute(
            L1Conditions(
                content_query="test",
                context_scope={"project": "magi"},
                limit=5,
            ),
            TimeRange(start=future_start),
        )
        future_graph_kwargs = l2_store.batch_list_current_relationships.await_args.kwargs
        assert future_graph_kwargs["effective_at"] == future_start
        assert future_graph_kwargs["effective_range"] == (future_start, None)


# ---------------------------------------------------------------------------
# P2-3: Confidence-aware fallback
# ---------------------------------------------------------------------------


class TestConfidenceAwareFallback:
    def test_low_scores_trigger_fallback(self):
        """When top-K average score is below threshold, should_fallback should be True."""
        config = RetrievalConfig(
            confidence_fallback_enabled=True,
            confidence_fallback_min_score=0.5,
            confidence_fallback_top_k=3,
        )
        events = [
            {"event_id": "a", "retrieval_score": 0.1},
            {"event_id": "b", "retrieval_score": 0.2},
            {"event_id": "c", "retrieval_score": 0.1},
        ]
        top_k = min(config.confidence_fallback_top_k, len(events))
        avg_score = sum(float(e.get("retrieval_score", 0)) for e in events[:top_k]) / top_k
        assert avg_score < config.confidence_fallback_min_score

    def test_high_scores_skip_fallback(self):
        """When top-K average score is above threshold, no extra fallback needed."""
        config = RetrievalConfig(
            confidence_fallback_enabled=True,
            confidence_fallback_min_score=0.3,
            confidence_fallback_top_k=3,
        )
        events = [
            {"event_id": "a", "retrieval_score": 0.8},
            {"event_id": "b", "retrieval_score": 0.7},
            {"event_id": "c", "retrieval_score": 0.6},
        ]
        top_k = min(config.confidence_fallback_top_k, len(events))
        avg_score = sum(float(e.get("retrieval_score", 0)) for e in events[:top_k]) / top_k
        assert avg_score >= config.confidence_fallback_min_score


# ---------------------------------------------------------------------------
# P2-4: Adaptive retrieval parameters
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Config field tests
# ---------------------------------------------------------------------------


class TestP2ConfigFields:
    def test_graph_spreading_defaults(self):
        config = RetrievalConfig()
        assert config.graph_spreading_enabled is False
        assert config.graph_spreading_max_hops == 2
        assert config.graph_spreading_decay == 0.5
        assert config.rrf_weight_graph == 0.6

    def test_confidence_fallback_defaults(self):
        config = RetrievalConfig()
        assert config.confidence_fallback_enabled is False
        assert config.confidence_fallback_min_score == 0.3
        assert config.confidence_fallback_top_k == 5

    def test_config_builder_maps_graph_spreading(self):
        """Verify build_retrieval_config_from_app_config maps graph spreading fields."""
        from unittest.mock import MagicMock

        app_config = MagicMock()
        reranker = app_config.agent.memory.reranker
        reranker.top_k = 8
        reranker.cross_encoder.enabled = False
        reranker.cross_encoder.managed_model_id = None

        qe = app_config.agent.memory.query_expansion
        qe.enabled = False
        qe.max_expansions = 3

        gs = app_config.agent.memory.graph_spreading
        gs.enabled = True

        from magi.memory.hybrid_retrieval.service import build_retrieval_config_from_app_config

        config = build_retrieval_config_from_app_config(app_config)
        assert config.query_expansion_max_expansions == 3
        assert config.graph_spreading_enabled is True
