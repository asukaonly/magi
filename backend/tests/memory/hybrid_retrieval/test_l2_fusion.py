"""Tests for L2 candidate fusion, domain weights, and structured filtering."""

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedConstraint,
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_fusion import (
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
    @pytest.mark.parametrize(
        "query_kind_value,domain_key,expected_weight",
        [
            pytest.param("preference", "knowledge_edge", 1.0, id="preference_knowledge_high"),
            pytest.param("temporal_episode", "episode", 1.0, id="temporal_episode_episode_high"),
            pytest.param("current_state", "assertion", 1.0, id="current_state_assertion_high"),
            pytest.param("unknown_kind", "knowledge_edge", 0.6, id="unknown_query_kind_fallback"),
        ],
    )
    def test_domain_weights_match_query_kind(self, query_kind_value, domain_key, expected_weight):
        w = get_domain_weight(query_kind_value, domain_key)
        assert w == expected_weight


class TestStructuredFiltering:


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
        assert [(candidate.candidate_id, candidate.kind) for candidate in result] == [
            ("t1", "knowledge_edge"),
            ("a1", "assertion"),
        ]
        assert result[0].payload == edges[0]
        assert result[1].payload == assertions[0]
        assert result[0].final_score > result[1].final_score > 0

    def test_subject_scope_excludes_wrong_person_while_retaining_matching_fact(self):
        plan = _make_plan()
        bad = {
            "triple_id": "wrong-person",
            "subject_id": "user:other",
            "predicate": "LIKES",
            "status": "active",
            "confidence": 0.9,
        }
        good = {**bad, "triple_id": "correct-person", "subject_id": "user:test"}
        probe = L2Candidate(candidate_id="wrong-person", kind="knowledge_edge", payload=bad)
        apply_structured_filter(probe, plan)
        assert (probe.gate_status, probe.gate_reason) == ("filtered", "subject_scope_mismatch")
        result = fuse_l2_candidates(
            plan, knowledge_edges=[bad, good], assertions=[], snapshots=[], episodes=[]
        )
        assert [(candidate.candidate_id, candidate.payload) for candidate in result] == [
            ("correct-person", good)
        ]

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
            knowledge_edges=[e2, e1],
            assertions=[],
            snapshots=[],
            episodes=[],
        )
        assert [candidate.candidate_id for candidate in result] == ["t1", "t2"]
        scores = {candidate.candidate_id: candidate.final_score for candidate in result}
        assert scores["t1"] > scores["t2"] > 0


class TestProjectCandidates:
    def test_projection_preserves_payload_and_score_evidence_in_each_domain(self):
        specifications = [
            ("t1", "knowledge_edge", {"triple_id": "t1", "predicate": "LIKES"}, 1.0, "relationships"),
            ("a1", "assertion", {"assertion_id": "a1", "value": "routine"}, 0.8, "assertions"),
            ("ep1", "episode", {"episode_id": "ep1", "summary": "event"}, 0.5, "episodes"),
            ("sn1", "snapshot", {"snapshot_id": "sn1", "entity_id": "person:1"}, 0.4, "entity_cards"),
            ("sh1", "snapshot_history", {"snapshot_id": "sh1", "version": 2}, 0.3, "state_history"),
        ]
        expected = {
            key: []
            for key in (
                "entity_cards",
                "relationships",
                "assertions",
                "episodes",
                "state_facts",
                "state_history",
                "trace",
            )
        }
        candidates = []
        for identity, kind, payload, score, group in specifications:
            trace = {"candidate_id": identity, "confidence": 0.7}
            candidates.append(
                L2Candidate(
                    candidate_id=identity, kind=kind, payload=payload, final_score=score, trace=trace
                )
            )
            expected[group].append({**payload, "_fusion_score": score, "_fusion_trace": trace})
        assert project_candidates(candidates) == expected
        assert all("_fusion_score" not in payload for _, _, payload, _, _ in specifications)
