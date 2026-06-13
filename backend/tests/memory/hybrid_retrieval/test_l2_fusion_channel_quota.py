"""Tests for the structured-channel reserved quota in fuse_l2_candidates.

Prevents the high-volume edge_vector channel from starving the precise
structured_graph channel when both compete for top_k slots.
RFC #65 follow-up — P1 (#94).
"""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_fusion import fuse_l2_candidates


def _make_plan(**kwargs) -> L2GroundingPlan:
    defaults = {
        "query_kind": "exact_fact",
        "subject_scope": "self",
        "subject_candidates": [
            GroundedEntityCandidate(
                entity_id="user:me",
                entity_type="person",
                surface="self",
                score=1.0,
            )
        ],
        "predicate_candidates": [
            GroundedPredicateCandidate(predicate="WORKS_AT", family="org"),
        ],
        "temporal_context": TemporalContext(mode="none"),
    }
    defaults.update(kwargs)
    return L2GroundingPlan(**defaults)


def _make_edge_vector_edge(i: int) -> dict:
    """Create a high-scoring edge_vector edge."""
    return {
        "triple_id": f"ev-{i}",
        "subject_id": "user:me",
        "predicate": "USES",
        "object_id": f"object:{i}",
        "object_type": "tool",
        "_hop": 1,
        "_subject_match_score": 1.0,
        "_predicate_match_score": 0.9,
        "_object_constraint_score": 1.0,
        "_temporal_score": 1.0,
        "status": "active",
        "confidence": 0.95,
        "observation_count": 10,
        "vector_distance": 0.05,  # very close — high semantic score
        "_channels": ["edge_vector"],
    }


def _make_structured_graph_edge(score_modifier: float = 0.0) -> dict:
    """Create a precise structured_graph edge with a low final_score."""
    return {
        "triple_id": "sg-precise-001",
        "subject_id": "user:me",
        "predicate": "WORKS_AT",
        "object_id": "company:acme",
        "object_type": "company",
        "_hop": 1,
        "_subject_match_score": 0.6,
        "_predicate_match_score": 0.6,
        "_object_constraint_score": 0.5,
        "_temporal_score": 1.0,
        "status": "active",
        "confidence": 0.5,
        "observation_count": 1,
        # No vector_distance — structured-only, no semantic evidence in this case.
        "_channels": ["structured_graph"],
    }


class TestStructuredChannelQuota:
    """The structured_graph channel must have reserved slots protected from
    being crowded out by high-volume edge_vector results."""

    def test_structured_candidate_retained_despite_lower_score(self):
        """Core quota test: 1 structured_graph edge with a lower final_score
        + 30 edge_vector edges with higher scores; top_k=8.

        The structured_graph edge MUST appear in the top_k result even though
        a pure global score-sort would drop it (it ranks ~31st by score).
        """
        plan = _make_plan()

        # 30 high-scoring edge_vector edges
        ev_edges = [_make_edge_vector_edge(i) for i in range(30)]

        # 1 low-scoring structured_graph edge (will be outscored by all 30 ev edges)
        sg_edge = _make_structured_graph_edge()

        all_edges = ev_edges + [sg_edge]

        results = fuse_l2_candidates(
            plan,
            knowledge_edges=all_edges,
            assertions=[],
            snapshots=[],
            episodes=[],
            top_k=8,
        )

        result_ids = [c.candidate_id for c in results]
        assert "sg-precise-001" in result_ids, (
            f"structured_graph edge was dropped by top_k=8 cut. "
            f"Result IDs: {result_ids}. "
            f"Scores: { {c.candidate_id: c.final_score for c in results} }"
        )

    def test_quota_does_not_fire_when_all_fit(self):
        """When total passed candidates <= top_k, ALL are returned (quota is a no-op)."""
        plan = _make_plan()

        # Only 5 edges total, top_k=8 → everything fits, no quota logic needed
        ev_edges = [_make_edge_vector_edge(i) for i in range(4)]
        sg_edge = _make_structured_graph_edge()

        all_edges = ev_edges + [sg_edge]

        results = fuse_l2_candidates(
            plan,
            knowledge_edges=all_edges,
            assertions=[],
            snapshots=[],
            episodes=[],
            top_k=8,
        )

        assert len(results) == 5, (
            f"Expected all 5 candidates when total <= top_k, got {len(results)}"
        )
        result_ids = [c.candidate_id for c in results]
        assert "sg-precise-001" in result_ids

    def test_quota_does_not_force_in_garbage_below_score_floor(self):
        """A structured_graph candidate with final_score below STRUCT_RESERVE_MIN_SCORE
        must NOT be force-reserved by the quota helper.

        Tests _select_with_channel_quota directly with a synthetic candidate whose
        final_score is explicitly set below the floor.
        """
        from magi.memory.hybrid_retrieval.l2_fusion import (
            STRUCT_RESERVE_MIN_SCORE,
            STRUCT_RESERVED_SLOTS,
            L2Candidate,
            _select_with_channel_quota,
        )

        # 10 high-scoring edge_vector candidates
        ev_candidates = [
            L2Candidate(
                candidate_id=f"ev-{i}",
                kind="knowledge_edge",
                payload={"_channels": ["edge_vector"]},
                retrieval_channels=["edge_vector"],
                final_score=0.9 - i * 0.01,
            )
            for i in range(10)
        ]

        # 1 structured_graph candidate with final_score BELOW the floor
        garbage_sg = L2Candidate(
            candidate_id="sg-garbage-001",
            kind="knowledge_edge",
            payload={"_channels": ["structured_graph"]},
            retrieval_channels=["structured_graph"],
            final_score=STRUCT_RESERVE_MIN_SCORE - 0.001,  # just below the floor
        )

        # Build sorted passed list (as fuse_l2_candidates would)
        passed = sorted(ev_candidates + [garbage_sg], key=lambda c: c.final_score, reverse=True)

        results = _select_with_channel_quota(passed, top_k=5)
        result_ids = [c.candidate_id for c in results]

        # The garbage structured edge must NOT be forced in by the quota
        assert "sg-garbage-001" not in result_ids, (
            f"Garbage structured_graph edge below score floor was incorrectly "
            f"forced into results. Score floor={STRUCT_RESERVE_MIN_SCORE}. "
            f"Results: {result_ids}"
        )

    def test_result_still_sorted_by_score(self):
        """After quota application, results must still be sorted by final_score descending."""
        plan = _make_plan()

        ev_edges = [_make_edge_vector_edge(i) for i in range(20)]
        sg_edge = _make_structured_graph_edge()

        results = fuse_l2_candidates(
            plan,
            knowledge_edges=ev_edges + [sg_edge],
            assertions=[],
            snapshots=[],
            episodes=[],
            top_k=8,
        )

        scores = [c.final_score for c in results]
        assert scores == sorted(scores, reverse=True), (
            f"Results are not sorted by final_score desc: {scores}"
        )

    def test_multiple_structured_edges_all_reserved(self):
        """When multiple structured_graph edges exist, up to STRUCT_RESERVED_SLOTS
        of them are guaranteed in the output (subject to score floor)."""
        from magi.memory.hybrid_retrieval.l2_fusion import STRUCT_RESERVED_SLOTS

        plan = _make_plan()

        # Many high-scoring ev edges
        ev_edges = [_make_edge_vector_edge(i) for i in range(30)]

        # 3 structured_graph edges with low-but-floor-clearing scores
        sg_edges = []
        for i in range(3):
            sg_edges.append({
                "triple_id": f"sg-multi-{i}",
                "subject_id": "user:me",
                "predicate": "WORKS_AT",
                "object_id": f"company:{i}",
                "_hop": 1,
                "_subject_match_score": 0.6,
                "_predicate_match_score": 0.6,
                "_object_constraint_score": 0.5,
                "_temporal_score": 1.0,
                "status": "active",
                "confidence": 0.5,
                "observation_count": 1,
                "_channels": ["structured_graph"],
            })

        results = fuse_l2_candidates(
            plan,
            knowledge_edges=ev_edges + sg_edges,
            assertions=[],
            snapshots=[],
            episodes=[],
            top_k=8,
        )

        result_ids = set(c.candidate_id for c in results)
        retained_sg = [eid for eid in result_ids if eid.startswith("sg-multi-")]
        expected_reserved = min(STRUCT_RESERVED_SLOTS, 3)
        assert len(retained_sg) >= expected_reserved, (
            f"Expected {expected_reserved} structured_graph edges reserved, "
            f"got {len(retained_sg)}. Result IDs: {sorted(result_ids)}"
        )
