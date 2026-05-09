"""Tests for knowledge hybrid retriever."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedConstraint,
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.l2_knowledge_retriever import (
    _merge_channels,
    _score_predicate_match,
    _score_subject_match,
    retrieve_knowledge,
)
from magi.memory.hybrid_retrieval.models import TemporalContext


def _make_store() -> MagicMock:
    store = MagicMock()
    store.get_relationships = AsyncMock(return_value=[])
    store.batch_get_relationships = AsyncMock(return_value={})
    store.search_edges_by_embedding = AsyncMock(return_value=[])
    store.filter_entity_ids_by_facet = AsyncMock(return_value=[])
    return store


def _make_plan(**kwargs) -> L2GroundingPlan:
    defaults = {
        "query_kind": "preference",
        "subject_candidates": [
            GroundedEntityCandidate(
                entity_id="user:test",
                entity_type="person",
                surface="self",
                score=1.0,
            )
        ],
        "predicate_candidates": [
            GroundedPredicateCandidate(predicate="LIKES", family="preference"),
        ],
        "temporal_context": TemporalContext(mode="none"),
    }
    defaults.update(kwargs)
    return L2GroundingPlan(**defaults)


class TestRetrieveKnowledge:
    @pytest.mark.asyncio
    async def test_runs_channels_concurrently(self):
        store = _make_store()
        now = time.time()
        store.batch_get_relationships.return_value = {
            "user:test": [
                {
                    "triple_id": "t1",
                    "subject_id": "user:test",
                    "predicate": "LIKES",
                    "object_id": "food:pizza",
                    "object_type": "food",
                    "first_observed_at": now,
                    "last_observed_at": now,
                },
            ],
        }
        plan = _make_plan()
        result = await retrieve_knowledge(plan, store)
        assert len(result) == 1
        assert result[0]["_candidate_kind"] == "knowledge_edge"

    @pytest.mark.asyncio
    async def test_without_embedding_service(self):
        store = _make_store()
        plan = _make_plan()
        result = await retrieve_knowledge(plan, store, embedding_service=None)
        store.search_edges_by_embedding.assert_not_called()
        assert result == [] or all(r.get("_channel") != "edge_vector" for r in result)


class TestMergeChannels:
    def test_deduplicates_by_triple_id(self):
        ch1 = [{"triple_id": "t1", "_channel": "graph", "data": "a"}]
        ch2 = [{"triple_id": "t1", "_channel": "vector", "data": "b", "vector_distance": 0.5}]
        merged = _merge_channels(ch1, ch2)
        assert len(merged) == 1
        assert merged[0]["vector_distance"] == 0.5
        assert len(merged[0]["_channels"]) == 2

    def test_keeps_unique_edges(self):
        ch1 = [{"triple_id": "t1", "_channel": "graph"}]
        ch2 = [{"triple_id": "t2", "_channel": "vector"}]
        merged = _merge_channels(ch1, ch2)
        assert len(merged) == 2


class TestScoring:
    def test_subject_match_present(self):
        plan = _make_plan()
        edge = {"subject_id": "user:test"}
        assert _score_subject_match(edge, plan) == 1.0

    def test_subject_match_missing(self):
        plan = _make_plan()
        edge = {"subject_id": "user:other"}
        assert _score_subject_match(edge, plan) == 0.0

    def test_predicate_match_expanded(self):
        plan = _make_plan()
        edge = {"predicate": "INTERESTED_IN"}
        score = _score_predicate_match(edge, plan)
        assert score == 1.0
