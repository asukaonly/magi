"""Tests for L2 fusion vector-driven scoring when predicate is missing (RFC #65 partial fix)."""

from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_fusion import L2Candidate, _compute_final_score


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
    `predicate_missing_vector_relevance`."""
    plan = _make_plan()

    c = L2Candidate(
        candidate_id="t",
        kind="knowledge_edge",
        payload={"vector_distance": 0.2},
        subject_match_score=1.0,
        predicate_match_score=0.5,
        object_constraint_score=1.0,
        status_score=1.0,
        retrieval_channels=["edge_vector"],
    )
    _compute_final_score(c, plan)
    assert "predicate_missing_vector_relevance" in c.trace


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
    """When predicate IS present, the vector-relevance trace key must NOT be written."""
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
    assert "predicate_missing_vector_relevance" not in c.trace
