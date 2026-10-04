"""Tests for L2 fusion vector-driven scoring when predicate is missing (RFC #65 partial fix)."""

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedConstraint,
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_fusion import fuse_l2_candidates


def _make_plan(**kwargs) -> L2GroundingPlan:
    defaults = {
        "query_kind": "unknown",
        "subject_scope": "self",
        "subject_candidates": [
            GroundedEntityCandidate(
                entity_id="user:test",
                entity_type="person",
                surface="self",
                score=1.0,
            )
        ],
        "predicate_candidates": [],
        "temporal_context": TemporalContext(mode="none"),
    }
    defaults.update(kwargs)
    return L2GroundingPlan(**defaults)


@pytest.mark.parametrize(
    "has_predicate,expected",
    [(False, ["near", "far", "fallback"]), (True, ["far", "near", "fallback"])],
)
def test_fusion_uses_vector_only_when_predicate_is_missing(has_predicate, expected):
    plan = _make_plan(
        predicate_candidates=(
            [GroundedPredicateCandidate(predicate="LIKES", family="preference")]
            if has_predicate
            else []
        )
    )
    common = {
        "subject_id": "user:test",
        "predicate": "LIKES",
        "object_id": "food:pizza",
        "status": "active",
        "_subject_match_score": 1.0,
        "_object_constraint_score": 1.0,
        "_temporal_score": 1.0,
        "_channels": ["structured_graph"],
    }
    edges = [
        common | {"triple_id": "fallback", "_predicate_match_score": 0.1},
        common | {"triple_id": "far", "_predicate_match_score": 1.0, "vector_distance": 9.0},
        common | {"triple_id": "near", "_predicate_match_score": 0.2, "vector_distance": 0.0},
    ]
    results = fuse_l2_candidates(
        plan, knowledge_edges=edges, assertions=[], snapshots=[], episodes=[]
    )
    assert [candidate.candidate_id for candidate in results] == expected
    assert results[0].final_score > results[1].final_score > results[2].final_score
    traces = {
        candidate.candidate_id: candidate.trace["predicate_missing_vector_relevance"]
        for candidate in results
    }
    assert traces == (
        {"near": None, "far": None, "fallback": None}
        if has_predicate
        else {"near": 1.0, "far": 0.1, "fallback": 0.0}
    )
    limited = fuse_l2_candidates(
        plan, knowledge_edges=edges, assertions=[], snapshots=[], episodes=[], top_k=1
    )
    assert [candidate.candidate_id for candidate in limited] == expected[:1]


# ---------------------------------------------------------------------------
# Structured channel abstain tests (CHANGE 1)
# ---------------------------------------------------------------------------


class TestStructuredChannelAbstain:
    """Tests that _structured_graph_channel abstains when it has no selective topical filter."""

    @pytest.mark.asyncio
    async def test_abstains_when_no_predicate_and_no_object_type(self):
        """With no predicate and no object-type constraint, _structured_graph_channel must
        return [] without calling batch_get_relationships or get_relationships."""
        from unittest.mock import AsyncMock, MagicMock

        from magi.memory.hybrid_retrieval.l2_knowledge_retriever import _structured_graph_channel

        store = MagicMock()
        store.batch_get_relationships = AsyncMock(return_value={})
        store.get_relationships = AsyncMock(return_value=[])

        # predicate_candidates=[] → expanded_predicates=[] → predicates=None
        # object_constraints=[] → _extract_object_types returns None
        plan = _make_plan(allow_soft_edges=False)  # isolate #67 hard-edge abstain (P2 soft layer off)

        result = await _structured_graph_channel(plan, store)

        assert result == [], f"expected abstain (empty list), got {result}"
        store.batch_get_relationships.assert_not_called()
        store.get_relationships.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_abstain_when_predicate_present(self):
        """When predicate IS present, the structured channel must still query."""
        from unittest.mock import AsyncMock, MagicMock

        from magi.memory.hybrid_retrieval.l2_knowledge_retriever import _structured_graph_channel

        store = MagicMock()
        store.batch_get_relationships = AsyncMock(return_value={
            "user:test": [
                {
                    "triple_id": "t1",
                    "subject_id": "user:test",
                    "predicate": "LIKES",
                    "object_id": "food:pizza",
                }
            ]
        })
        store.get_relationships = AsyncMock(return_value=[])

        plan = _make_plan(
            allow_soft_edges=False,  # isolate #67 hard-edge query decision (P2 soft layer off)
            predicate_candidates=[
                GroundedPredicateCandidate(predicate="LIKES", family="preference"),
            ],
        )

        result = await _structured_graph_channel(plan, store)

        store.batch_get_relationships.assert_called_once()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_object_type_constraint_reaches_actual_structured_fetch(self):
        from unittest.mock import AsyncMock, MagicMock
        from magi.memory.hybrid_retrieval.l2_knowledge_retriever import _structured_graph_channel

        edge = {
            "triple_id": "software-edge",
            "subject_id": "user:test",
            "predicate": "USES",
            "object_id": "software:editor",
            "object_type": "software",
        }
        store = MagicMock(
            batch_get_relationships=AsyncMock(return_value={"user:test": [edge]}),
            get_relationships=AsyncMock(return_value=[]),
        )
        plan = _make_plan(
            allow_soft_edges=False,
            object_constraints=[
                GroundedConstraint(field="object_type", operator="eq", value="software", confidence=0.9)
            ],
        )
        result = await _structured_graph_channel(plan, store, limit=7)
        store.batch_get_relationships.assert_awaited_once_with(
            entity_ids=["user:test"],
            direction="outgoing",
            status_filters=["active"],
            predicates=None,
            object_types=["software"],
            limit_per_entity=7,
            evidence_classes=None,
            temporal_clause=None,
        )
        store.get_relationships.assert_not_awaited()
        assert result == [edge | {"_channel": "structured_graph"}]


# ---------------------------------------------------------------------------
# Soft-edge fusion scoring tests (RFC #65 P2 Task 6)
# ---------------------------------------------------------------------------


def test_fusion_orders_soft_edges_by_confidence_despite_conflicting_vectors():
    common = {
        "subject_id": "user:test",
        "predicate": "SEMANTIC_CONTEXT",
        "fact_kind": "semantic_edge",
        "object_id": "topic:test",
        "status": "active",
        "_subject_match_score": 1.0,
        "_object_constraint_score": 1.0,
        "_channels": ["structured_graph"],
    }
    edges = [
        common | {"triple_id": "low", "confidence": 0.1, "vector_distance": 0.0},
        common | {"triple_id": "high", "confidence": 0.9, "vector_distance": 100.0},
    ]
    results = fuse_l2_candidates(
        _make_plan(), knowledge_edges=edges, assertions=[], snapshots=[], episodes=[]
    )
    assert [candidate.candidate_id for candidate in results] == ["high", "low"]
    assert results[0].final_score > results[1].final_score > 0
    assert [candidate.trace["confidence"] for candidate in results] == [0.9, 0.1]
    assert all(candidate.trace["soft_edge"] is True for candidate in results)
    assert all(
        candidate.trace["predicate_missing_vector_relevance"] is None for candidate in results
    )


def test_fusion_traces_hops_and_preserves_controlled_edge_decay():
    plan = _make_plan(
        query_kind="exact_fact",
        predicate_candidates=[GroundedPredicateCandidate(predicate="LIKES")],
        hop2_target_type="person",
    )
    common = {
        "subject_id": "user:test",
        "predicate": "LIKES",
        "object_id": "object:test",
        "status": "active",
        "_subject_match_score": 1.0,
        "_predicate_match_score": 1.0,
        "_object_constraint_score": 1.0,
        "confidence": 1.0,
        "observation_count": 5,
        "_channels": ["structured_graph"],
    }
    edges = [
        common | {"triple_id": "speculative", "_hop": 2, "object_type": "company"},
        common
        | {"triple_id": "soft", "predicate": "SEMANTIC_CONTEXT", "fact_kind": "semantic_edge"},
        common | {"triple_id": "answer", "_hop": 2, "object_type": "person"},
        common | {"triple_id": "direct", "object_type": "person"},
    ]
    results = fuse_l2_candidates(
        plan, knowledge_edges=edges, assertions=[], snapshots=[], episodes=[]
    )
    by_id = {candidate.candidate_id: candidate for candidate in results}
    assert set(by_id) == {"speculative", "soft", "answer", "direct"}
    assert {key: value.final_score for key, value in by_id.items()} == {
        "direct": 1.0,
        "answer": 1.0,
        "soft": 0.6,
        "speculative": 0.5,
    }
    assert {key: value.trace["hop"] for key, value in by_id.items()} == {
        "direct": 1,
        "answer": 2,
        "soft": 1,
        "speculative": 2,
    }
    assert {key: value.trace["soft_edge"] for key, value in by_id.items()} == {
        "direct": False,
        "answer": False,
        "soft": True,
        "speculative": False,
    }


# ---------------------------------------------------------------------------
# hop2 edge scoring and gate tests (RFC #65 P3 Task 5)
# ---------------------------------------------------------------------------


def test_hop2_edge_exempt_from_subject_gate():
    from magi.memory.hybrid_retrieval.l2_fusion import apply_structured_filter, L2Candidate
    from magi.memory.hybrid_retrieval.grounding import L2GroundingPlan, GroundedEntityCandidate
    plan = L2GroundingPlan(subject_scope="self",
                           subject_candidates=[GroundedEntityCandidate(
                               entity_id="user:u1", entity_type="person", surface="self", score=1.0)])
    hop2 = L2Candidate(candidate_id="x", kind="knowledge_edge",
                       payload={"subject_id": "person:artist", "_hop": 2, "status": "active"})
    apply_structured_filter(hop2, plan)
    assert hop2.gate_status != "filtered"  # exempt

    non_hop2 = L2Candidate(candidate_id="y", kind="knowledge_edge",
                           payload={"subject_id": "person:artist", "status": "active"})
    apply_structured_filter(non_hop2, plan)
    assert non_hop2.gate_status == "filtered"  # #67 gate still bites non-hop2
