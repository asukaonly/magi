"""Tests for L2 query grounding."""

import pytest

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
    build_grounding_plan,
)
from magi.memory.hybrid_retrieval.models import (
    L2Conditions,
    L2SemanticFrame,
    SemanticConstraint,
    TemporalContext,
    TimeRange,
)


class TestBuildGroundingPlan:
    def test_basic_self_preference_query(self):
        conditions = L2Conditions(
            content_query="what books do I like",
            predicate_family="preference",
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="topic",
                answer_unit="identity",
            ),
        )
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="test_user",
        )
        assert plan.subject_scope == "self"
        assert len(plan.subject_candidates) == 1
        assert plan.subject_candidates[0].entity_id == "user:test_user"
        assert plan.query_kind == "preference"
        assert len(plan.predicate_candidates) > 0

    def test_explicit_predicates(self):
        conditions = L2Conditions(
            content_query="test",
            predicates=["LIKES", "DISLIKES"],
        )
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="u1",
        )
        assert len(plan.predicate_candidates) == 2
        assert plan.predicate_candidates[0].predicate == "LIKES"

    def test_expanded_predicates(self):
        conditions = L2Conditions(
            content_query="test",
            predicates=["LIKES"],
        )
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="u1",
        )
        expanded = plan.expanded_predicates
        assert "LIKES" in expanded
        assert "INTERESTED_IN" in expanded

    def test_temporal_context_from_time_range(self):
        conditions = L2Conditions(content_query="test")
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="u1",
            time_range=TimeRange(start=100.0, end=200.0),
        )
        assert plan.temporal_context.mode == "during"
        assert plan.temporal_context.start == 100.0

    def test_resolved_entities_become_object_candidates(self):
        conditions = L2Conditions(content_query="test")
        entities = [
            {"entity_id": "e1", "entity_type": "software", "canonical_name": "VS Code", "confidence": 0.9},
        ]
        plan = build_grounding_plan(
            conditions,
            resolved_entities=entities,
            user_id="u1",
        )
        assert len(plan.object_candidates) == 1
        assert plan.object_candidates[0].entity_id == "e1"

    def test_confidence_computation(self):
        conditions = L2Conditions(
            content_query="test",
            predicates=["LIKES"],
        )
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="u1",
        )
        assert 0.0 < plan.confidence <= 1.0

    def test_no_user_id_no_default_subject(self):
        conditions = L2Conditions(content_query="test")
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id=None,
        )
        assert plan.subject_scope == "none"
        assert len(plan.subject_candidates) == 0

    def test_entity_type_constraint(self):
        conditions = L2Conditions(
            content_query="test",
            entity_types=["software"],
        )
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="u1",
        )
        assert any(c.field == "object_type" for c in plan.object_constraints)

    def test_semantic_constraint_forwarded(self):
        conditions = L2Conditions(
            content_query="test",
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="creator",
                answer_unit="identity",
                constraints=[SemanticConstraint(
                    scope="target",
                    facet="platform",
                    raw_value="YouTube",
                    resolved_entity_id="software:youtube",
                )],
            ),
        )
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="u1",
        )
        assert any(c.field == "platform" for c in plan.object_constraints)


def test_grounding_propagates_allowed_evidence_classes():
    conditions = L2Conditions(
        subject_hint="self",
        predicate_family="preference",
        allowed_evidence_classes={EvidenceClass.USER_SELF_REPORT.label},
    )
    plan = build_grounding_plan(
        conditions, resolved_entities=[], user_id="local_user", time_range=None
    )
    assert plan.allowed_evidence_classes == {EvidenceClass.USER_SELF_REPORT.label}
