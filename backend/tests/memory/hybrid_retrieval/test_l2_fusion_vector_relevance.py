"""Tests for L2 fusion vector-driven scoring when predicate is missing (RFC #65 partial fix)."""

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedConstraint,
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_fusion import L2Candidate, _compute_final_score, fuse_l2_candidates


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


def test_predicate_missing_lets_vector_drive_relevance():
    """When predicate can't be inferred, edge-vector semantic similarity must drive rank.

    A semantically-near edge (small vector_distance) must score higher than a
    structured-only fallback edge (no vector_distance → no semantic evidence).
    """
    plan = _make_plan()  # predicate_candidates=[]

    near = L2Candidate(
        candidate_id="near",
        kind="knowledge_edge",
        payload={"vector_distance": 0.3},
        subject_match_score=1.0,
        predicate_match_score=0.5,
        object_constraint_score=1.0,
        status_score=1.0,
        retrieval_channels=["edge_vector"],
    )
    fallback = L2Candidate(
        candidate_id="fb",
        kind="knowledge_edge",
        payload={},  # no vector_distance — structured fallback with no semantic evidence
        subject_match_score=1.0,
        predicate_match_score=0.5,
        object_constraint_score=1.0,
        status_score=1.0,
        retrieval_channels=["structured_graph"],
    )

    # With predicate missing, the semantically-near edge must outrank the
    # no-semantic-evidence fallback edge.
    assert _compute_final_score(near, plan) > _compute_final_score(fallback, plan)


def test_predicate_missing_no_vector_distance_scores_lower_than_vector_hit():
    """Structured-only edge (no vector_distance) gets 0 for the predicate/vector slot,
    so it scores below any edge that has real semantic evidence."""
    plan = _make_plan()  # predicate_candidates=[]

    vector_edge = L2Candidate(
        candidate_id="v",
        kind="knowledge_edge",
        payload={"vector_distance": 0.5},  # moderate semantic match
        subject_match_score=0.8,
        predicate_match_score=0.5,
        object_constraint_score=1.0,
        status_score=1.0,
        retrieval_channels=["edge_vector"],
    )
    structured_only = L2Candidate(
        candidate_id="s",
        kind="knowledge_edge",
        payload={},
        subject_match_score=0.8,
        predicate_match_score=0.5,
        object_constraint_score=1.0,
        status_score=1.0,
        retrieval_channels=["structured_graph"],
    )

    assert _compute_final_score(vector_edge, plan) > _compute_final_score(structured_only, plan)


def test_predicate_missing_trace_key_written():
    """When predicate is missing and vector_distance is present, the trace must record
    `predicate_missing_vector_relevance` through the full production path
    (fuse_l2_candidates → _compute_final_score → _build_score_trace)."""
    plan = _make_plan()  # predicate_candidates=[]

    edge = {
        "triple_id": "t1",
        "subject_id": "user:test",
        "predicate": "USES",
        "object_id": "tool:x",
        "vector_distance": 0.2,
        "_subject_match_score": 1.0,
        "_predicate_match_score": 0.5,
        "_object_constraint_score": 1.0,
        "_temporal_score": 1.0,
        "status": "active",
        "_channels": ["edge_vector"],
    }

    results = fuse_l2_candidates(
        plan,
        knowledge_edges=[edge],
        assertions=[],
        snapshots=[],
        episodes=[],
    )
    assert results, "expected one candidate back"
    c = results[0]
    # The trace key must survive through _build_score_trace.
    assert "predicate_missing_vector_relevance" in c.trace, (
        f"key missing from trace; trace={c.trace}"
    )
    expected = round(1.0 / (1.0 + 0.2), 4)
    assert c.trace["predicate_missing_vector_relevance"] == pytest.approx(expected), (
        f"wrong value; got {c.trace['predicate_missing_vector_relevance']}"
    )


def test_predicate_present_trace_key_is_none():
    """When predicate IS present, trace['predicate_missing_vector_relevance'] must be None."""
    plan = _make_plan(
        predicate_candidates=[
            GroundedPredicateCandidate(predicate="LIKES", family="preference"),
        ],
    )
    edge = {
        "triple_id": "t2",
        "subject_id": "user:test",
        "predicate": "LIKES",
        "object_id": "food:pizza",
        "vector_distance": 0.1,
        "_subject_match_score": 1.0,
        "_predicate_match_score": 1.0,
        "_object_constraint_score": 1.0,
        "_temporal_score": 1.0,
        "status": "active",
        "_channels": ["structured_graph"],
    }
    results = fuse_l2_candidates(
        plan,
        knowledge_edges=[edge],
        assertions=[],
        snapshots=[],
        episodes=[],
    )
    assert results, "expected one candidate back"
    c = results[0]
    assert c.trace.get("predicate_missing_vector_relevance") is None, (
        f"key should be None when predicate is present; got {c.trace.get('predicate_missing_vector_relevance')}"
    )


def test_predicate_present_behavior_unchanged():
    """When predicate IS inferred, the original predicate_match_score path must be used,
    not the vector path."""
    plan = _make_plan(
        predicate_candidates=[
            GroundedPredicateCandidate(predicate="LIKES", family="preference"),
        ],
    )

    hit = L2Candidate(
        candidate_id="hit",
        kind="knowledge_edge",
        payload={},
        subject_match_score=1.0,
        predicate_match_score=1.0,
        object_constraint_score=1.0,
        status_score=1.0,
        retrieval_channels=["structured_graph"],
    )
    miss = L2Candidate(
        candidate_id="miss",
        kind="knowledge_edge",
        payload={},
        subject_match_score=1.0,
        predicate_match_score=0.2,
        object_constraint_score=1.0,
        status_score=1.0,
        retrieval_channels=["structured_graph"],
    )

    # predicate_match drives ranking when predicate is present
    assert _compute_final_score(hit, plan) > _compute_final_score(miss, plan)


def test_predicate_present_no_trace_key():
    """When predicate IS present, predicate_missing_vector_relevance must NOT be set
    on the candidate (remains None) after _compute_final_score."""
    plan = _make_plan(
        predicate_candidates=[
            GroundedPredicateCandidate(predicate="USES", family="activity"),
        ],
    )
    c = L2Candidate(
        candidate_id="x",
        kind="knowledge_edge",
        payload={"vector_distance": 0.1},
        subject_match_score=1.0,
        predicate_match_score=0.9,
        object_constraint_score=1.0,
        status_score=1.0,
        retrieval_channels=["edge_vector"],
    )
    _compute_final_score(c, plan)
    # The dataclass field stays None — the vector-relevance shortcut was not taken.
    assert c.predicate_missing_vector_relevance is None


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
    async def test_does_not_abstain_when_object_type_constraint_present(self):
        """Even with no predicate, an object-type constraint is topically selective —
        the structured channel must still query."""
        from unittest.mock import AsyncMock, MagicMock

        from magi.memory.hybrid_retrieval.l2_knowledge_retriever import _structured_graph_channel

        store = MagicMock()
        store.batch_get_relationships = AsyncMock(return_value={})
        store.get_relationships = AsyncMock(return_value=[])

        plan = _make_plan(
            object_constraints=[
                GroundedConstraint(
                    field="object_type",
                    operator="eq",
                    value="software",
                    confidence=0.9,
                ),
            ],
        )

        await _structured_graph_channel(plan, store)

        # Should have called the store (not abstained).
        assert (
            store.batch_get_relationships.called or store.get_relationships.called
        ), "expected store query when object_type constraint is present"


# ---------------------------------------------------------------------------
# Soft-edge fusion scoring tests (RFC #65 P2 Task 6)
# ---------------------------------------------------------------------------


def test_soft_edge_scored_by_confidence_not_vector():
    """Soft edge (no vector_distance) must score via confidence, not sink to 0."""
    from magi.memory.hybrid_retrieval.l2_fusion import _compute_final_score, L2Candidate
    from magi.memory.hybrid_retrieval.grounding import L2GroundingPlan

    plan = L2GroundingPlan()  # predicate_candidates empty → #67 path for hard edges
    soft = L2Candidate(
        candidate_id="s1", kind="knowledge_edge",
        payload={"predicate": "SEMANTIC_CONTEXT", "fact_kind": "semantic_edge",
                 "confidence": 0.9},
        subject_match_score=1.0, object_constraint_score=1.0,
        confidence_score=0.9,
    )
    score = _compute_final_score(soft, plan)
    assert score > 0.0


def test_soft_edge_ranks_below_comparable_hard_edge():
    from magi.memory.hybrid_retrieval.l2_fusion import _compute_final_score, L2Candidate
    from magi.memory.hybrid_retrieval.grounding import L2GroundingPlan, GroundedPredicateCandidate

    plan = L2GroundingPlan(predicate_candidates=[GroundedPredicateCandidate(predicate="LIKES")])
    common = dict(subject_match_score=1.0, object_constraint_score=1.0, confidence_score=0.9)
    hard = L2Candidate(candidate_id="h", kind="knowledge_edge",
                       payload={"predicate": "LIKES"}, predicate_match_score=1.0, **common)
    soft = L2Candidate(candidate_id="s", kind="knowledge_edge",
                       payload={"predicate": "SEMANTIC_CONTEXT", "fact_kind": "semantic_edge"},
                       predicate_match_score=1.0, **common)
    hs = _compute_final_score(hard, plan)
    ss = _compute_final_score(soft, plan)
    assert ss < hs


def test_soft_edge_flag_in_trace():
    from magi.memory.hybrid_retrieval.l2_fusion import _build_score_trace, L2Candidate
    soft = L2Candidate(candidate_id="s", kind="knowledge_edge",
                       payload={"predicate": "SEMANTIC_CONTEXT", "fact_kind": "semantic_edge"})
    hard = L2Candidate(candidate_id="h", kind="knowledge_edge", payload={"predicate": "LIKES"})
    assert _build_score_trace(soft)["soft_edge"] is True
    assert _build_score_trace(hard)["soft_edge"] is False


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


def test_hop2_edge_scored_by_confidence_and_decayed_below_hop1():
    from magi.memory.hybrid_retrieval.l2_fusion import _compute_final_score, L2Candidate
    from magi.memory.hybrid_retrieval.grounding import L2GroundingPlan, GroundedPredicateCandidate
    plan = L2GroundingPlan(predicate_candidates=[GroundedPredicateCandidate(predicate="LIKES")])
    hop1 = L2Candidate(candidate_id="h1", kind="knowledge_edge",
                       payload={"predicate": "LIKES"},
                       subject_match_score=1.0, predicate_match_score=1.0,
                       object_constraint_score=1.0, confidence_score=0.9)
    hop2 = L2Candidate(candidate_id="h2", kind="knowledge_edge",
                       payload={"predicate": "CREATES", "_hop": 2},
                       subject_match_score=0.0,
                       object_constraint_score=1.0, confidence_score=0.9)
    hs = _compute_final_score(hop1, plan)
    h2s = _compute_final_score(hop2, plan)
    assert h2s > 0.0
    assert h2s < hs


def test_hop2_in_trace():
    from magi.memory.hybrid_retrieval.l2_fusion import _build_score_trace, L2Candidate
    hop2 = L2Candidate(candidate_id="h2", kind="knowledge_edge", payload={"_hop": 2})
    hop1 = L2Candidate(candidate_id="h1", kind="knowledge_edge", payload={"predicate": "LIKES"})
    assert _build_score_trace(hop2)["hop"] == 2
    assert _build_score_trace(hop1)["hop"] == 1
