"""Tests for knowledge hybrid retriever."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.l2_knowledge_retriever import (
    _merge_channels,
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
    async def test_structured_and_vector_channels_start_before_either_completes(self):
        import asyncio
        from types import SimpleNamespace

        store = _make_store()
        graph_entered, embedding_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def graph(**kwargs):
            graph_entered.set()
            await release.wait()
            return {
                "user:test": [
                    {
                        "triple_id": "graph-1",
                        "subject_id": "user:test",
                        "predicate": "INTERESTED_IN",
                        "object_id": "topic:rust",
                        "status": "active",
                    }
                ]
            }

        async def embed(text):
            embedding_entered.set()
            await release.wait()
            return [1.0, 0.0]

        store.batch_get_relationships.side_effect = graph
        store.search_edges_by_embedding.return_value = [
            {
                "triple_id": "vector-1",
                "subject_id": "user:test",
                "predicate": "USES",
                "object_id": "tool:editor",
                "vector_distance": 0.2,
            }
        ]
        embedding = SimpleNamespace(embed_text=AsyncMock(side_effect=embed))
        task = asyncio.create_task(
            retrieve_knowledge(
                _make_plan(allow_soft_edges=False),
                store,
                embedding_service=embedding,
                edge_vector_index=object(),
            )
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(graph_entered.wait(), embedding_entered.wait()), timeout=2
            )
            assert not task.done()
            store.search_edges_by_embedding.assert_not_awaited()
        finally:
            release.set()
            result = await asyncio.wait_for(task, timeout=2)
        assert [edge["triple_id"] for edge in result] == ["graph-1", "vector-1"]
        assert result[0]["_channels"] == ["structured_graph"]
        assert result[0]["_predicate_match_score"] == 1.0
        assert result[1]["_channels"] == ["edge_vector"]
        assert all(edge["_candidate_kind"] == "knowledge_edge" for edge in result)
        store.batch_get_relationships.assert_awaited_once()
        assert "INTERESTED_IN" in store.batch_get_relationships.await_args.kwargs["predicates"]
        store.search_edges_by_embedding.assert_awaited_once()

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

    def test_merging_distinct_channels_keeps_each_fact_and_its_provenance(self):
        graph = [
            {"triple_id": "t1", "_channel": "graph", "predicate": "LIKES", "object_id": "food:pizza"}
        ]
        vector = [
            {"triple_id": "t2", "_channel": "vector", "predicate": "USES", "object_id": "tool:editor"}
        ]
        assert _merge_channels(graph, vector) == [
            {
                "triple_id": "t1",
                "_channel": "graph",
                "predicate": "LIKES",
                "object_id": "food:pizza",
                "_channels": ["graph"],
            },
            {
                "triple_id": "t2",
                "_channel": "vector",
                "predicate": "USES",
                "object_id": "tool:editor",
                "_channels": ["vector"],
            },
        ]


class TestScoring:
    @pytest.mark.parametrize(
        "subject_id,expected_score",
        [
            pytest.param("user:test", 1.0, id="subject_match_present"),
            pytest.param("user:other", 0.0, id="subject_match_missing"),
        ],
    )
    def test_subject_match_scores_identity(self, subject_id, expected_score):
        plan = _make_plan()
        edge = {"subject_id": subject_id}
        assert _score_subject_match(edge, plan) == expected_score
