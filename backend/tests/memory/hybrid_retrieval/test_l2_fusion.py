"""Tests for L2 candidate fusion, domain weights, and structured filtering."""

import time

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedConstraint,
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_fusion import (
    DOMAIN_WEIGHTS,
    L2Candidate,
    apply_structured_filter,
    fuse_l2_candidates,
    get_domain_weight,
    project_candidates,
)


def _make_plan(**kwargs) -> L2GroundingPlan:
    defaults = {
        "query_kind": "preference",
        "subject_scope": "self",
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


class TestDomainWeights:
    def test_preference_knowledge_high(self):
        w = get_domain_weight("preference", "knowledge_edge")
        assert w == 1.0

    def test_temporal_episode_episode_high(self):
        w = get_domain_weight("temporal_episode", "episode")
        assert w == 1.0

    def test_current_state_assertion_high(self):
        w = get_domain_weight("current_state", "assertion")
        assert w == 1.0

    def test_unknown_query_kind_fallback(self):
        w = get_domain_weight("unknown_kind", "knowledge_edge")
        assert w == 0.6


class TestStructuredFiltering:
    def test_subject_scope_mismatch_filtered(self):
        plan = _make_plan()
        c = L2Candidate(
            candidate_id="t1",
            kind="knowledge_edge",
            payload={"subject_id": "user:other"},
        )
        apply_structured_filter(c, plan)
        assert c.gate_status == "filtered"
        assert c.gate_reason == "subject_scope_mismatch"

    def test_subject_scope_match_passes(self):
        plan = _make_plan()
        c = L2Candidate(
            candidate_id="t1",
            kind="knowledge_edge",
            payload={"subject_id": "user:test"},
        )
        apply_structured_filter(c, plan)
        assert c.gate_status == "pass"

    def test_object_type_high_confidence_filtered(self):
        plan = _make_plan(
            object_constraints=[
                GroundedConstraint(field="object_type", operator="in", value="food", confidence=0.9),
            ],
        )
        c = L2Candidate(
            candidate_id="t1",
            kind="knowledge_edge",
            payload={"subject_id": "user:test", "object_type": "software"},
        )
        apply_structured_filter(c, plan)
        assert c.gate_status == "filtered"
        assert c.gate_reason == "object_type_mismatch"

    def test_object_type_low_confidence_passes(self):
        plan = _make_plan(
            object_constraints=[
                GroundedConstraint(field="object_type", operator="in", value="food", confidence=0.5),
            ],
        )
        c = L2Candidate(
            candidate_id="t1",
            kind="knowledge_edge",
            payload={"subject_id": "user:test", "object_type": "software"},
        )
        apply_structured_filter(c, plan)
        assert c.gate_status == "pass"

    def test_temporal_invalid_filtered(self):
        plan = _make_plan(
            temporal_context=TemporalContext(mode="during", start=100.0, end=200.0, confidence=0.9),
        )
        c = L2Candidate(
            candidate_id="t1",
            kind="knowledge_edge",
            payload={"subject_id": "user:test"},
            temporal_score=0.0,
        )
        apply_structured_filter(c, plan)
        assert c.gate_status == "filtered"
        assert c.gate_reason == "time_invalid"


class TestFuseCandidates:
    def test_basic_fusion(self):
        plan = _make_plan()
        now = time.time()
        edges = [
            {
                "triple_id": "t1",
                "subject_id": "user:test",
                "predicate": "LIKES",
                "object_id": "food:pizza",
                "object_type": "food",
                "status": "active",
                "natural_summary": "likes pizza",
                "_temporal_score": 1.0,
                "_subject_match_score": 1.0,
                "_predicate_match_score": 1.0,
                "_object_constraint_score": 1.0,
                "_channels": ["structured_graph"],
                "confidence": 0.9,
                "observation_count": 3,
            },
        ]
        assertions = [
            {
                "assertion_id": "a1",
                "natural_summary": "prefers Italian",
                "_temporal_score": 0.8,
                "_candidate_kind": "assertion",
                "confidence_score": 0.7,
            },
        ]
        result = fuse_l2_candidates(
            plan,
            knowledge_edges=edges,
            assertions=assertions,
            snapshots=[],
            episodes=[],
        )
        assert len(result) == 2
        assert result[0].final_score > 0

    def test_filtered_candidates_excluded(self):
        plan = _make_plan()
        edges = [
            {
                "triple_id": "t1",
                "subject_id": "user:other",  # wrong subject
                "predicate": "LIKES",
                "status": "active",
                "_temporal_score": 1.0,
                "_channels": [],
                "confidence": 0.5,
            },
        ]
        result = fuse_l2_candidates(
            plan,
            knowledge_edges=edges,
            assertions=[],
            snapshots=[],
            episodes=[],
        )
        assert len(result) == 0

    def test_multi_channel_boost(self):
        plan = _make_plan(subject_scope="none", subject_candidates=[])
        e1 = {
            "triple_id": "t1",
            "subject_id": "user:test",
            "predicate": "LIKES",
            "status": "active",
            "_temporal_score": 1.0,
            "_subject_match_score": 0.5,
            "_predicate_match_score": 1.0,
            "_channels": ["structured_graph", "edge_vector"],
            "confidence": 0.8,
            "observation_count": 2,
        }
        e2 = {
            "triple_id": "t2",
            "subject_id": "user:test",
            "predicate": "LIKES",
            "status": "active",
            "_temporal_score": 1.0,
            "_subject_match_score": 0.5,
            "_predicate_match_score": 1.0,
            "_channels": ["structured_graph"],
            "confidence": 0.8,
            "observation_count": 2,
        }
        result = fuse_l2_candidates(
            plan,
            knowledge_edges=[e1, e2],
            assertions=[],
            snapshots=[],
            episodes=[],
        )
        assert result[0].final_score >= result[1].final_score


class TestProjectCandidates:
    def test_projection_groups(self):
        candidates = [
            L2Candidate(candidate_id="t1", kind="knowledge_edge", payload={"triple_id": "t1"}, final_score=1.0),
            L2Candidate(candidate_id="a1", kind="assertion", payload={"assertion_id": "a1"}, final_score=0.8),
            L2Candidate(candidate_id="ep1", kind="episode", payload={"episode_id": "ep1"}, final_score=0.5),
        ]
        result = project_candidates(candidates)
        assert len(result["relationships"]) == 1
        assert len(result["assertions"]) == 1
        assert len(result["episodes"]) == 1
