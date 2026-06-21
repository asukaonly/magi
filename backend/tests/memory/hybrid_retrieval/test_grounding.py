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

    def test_explicit_subject_hint_binds_first_resolved_entity_as_subject(self):
        conditions = L2Conditions(
            content_query="What is Caroline's relationship status?",
            subject_hint="explicit",
            predicate_family="relationship",
        )
        entities = [
            {
                "entity_id": "person:caroline",
                "entity_type": "person",
                "canonical_name": "Caroline",
                "confidence": 0.95,
                "match_source": "exact",
            },
        ]
        plan = build_grounding_plan(
            conditions,
            resolved_entities=entities,
            user_id="benchmark/locomo/run/conv-26",
        )
        assert plan.subject_scope == "explicit"
        assert [candidate.entity_id for candidate in plan.subject_candidates] == ["person:caroline"]
        assert plan.object_candidates == []

    def test_explicit_semantic_frame_binds_mentioned_entity_as_subject(self):
        conditions = L2Conditions(
            content_query="What does Melanie think about Caroline?",
            semantic_frame=L2SemanticFrame(
                query_family="profile",
                subject_scope="explicit",
                answer_kind="topic",
                answer_unit="mixed",
                entity_mentions=["Melanie", "Caroline"],
            ),
        )
        entities = [
            {
                "entity_id": "person:caroline",
                "entity_type": "person",
                "canonical_name": "Caroline",
                "confidence": 0.95,
                "match_source": "exact",
            },
            {
                "entity_id": "person:melanie",
                "entity_type": "person",
                "canonical_name": "Melanie",
                "confidence": 0.95,
                "match_source": "exact",
            },
        ]
        plan = build_grounding_plan(
            conditions,
            resolved_entities=entities,
            user_id="benchmark/locomo/run/conv-26",
        )
        assert [candidate.entity_id for candidate in plan.subject_candidates] == ["person:melanie"]
        assert [candidate.entity_id for candidate in plan.object_candidates] == ["person:caroline"]

    def test_collective_person_query_binds_all_people_not_self_or_first_only(self):
        conditions = L2Conditions(
            content_query="What animal do both Nate and Joanna like?",
            subject_hint="self",
            predicate_family="preference",
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="explicit",
                answer_kind="topic",
                answer_unit="mixed",
                entity_mentions=["Nate", "Joanna"],
            ),
        )
        entities = [
            {
                "entity_id": "person:nate",
                "entity_type": "person",
                "canonical_name": "Nate",
                "confidence": 0.95,
                "match_source": "exact",
            },
            {
                "entity_id": "person:joanna",
                "entity_type": "person",
                "canonical_name": "Joanna",
                "confidence": 0.95,
                "match_source": "exact",
            },
        ]
        plan = build_grounding_plan(
            conditions,
            resolved_entities=entities,
            user_id="benchmark/locomo/run/conv-42",
        )
        assert plan.subject_scope == "multi"
        assert [candidate.entity_id for candidate in plan.subject_candidates] == [
            "person:nate",
            "person:joanna",
        ]
        assert plan.object_candidates == []

    def test_role_aware_shared_fact_binds_all_subject_mentions(self):
        conditions = L2Conditions(
            content_query="What animal do both Nate and Joanna like?",
            subject_hint="explicit",
            predicate_family="preference",
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="multi",
                subject_mode="multi",
                relation_shape="shared_fact",
                subject_mentions=["Nate", "Joanna"],
                object_mentions=[],
                entity_mentions=["Nate", "Joanna"],
                answer_kind="topic",
            ),
        )
        entities = [
            {
                "entity_id": "person:joanna",
                "entity_type": "person",
                "canonical_name": "Joanna",
                "confidence": 0.95,
                "match_source": "exact",
            },
            {
                "entity_id": "person:nate",
                "entity_type": "person",
                "canonical_name": "Nate",
                "confidence": 0.95,
                "match_source": "exact",
            },
        ]

        plan = build_grounding_plan(
            conditions,
            resolved_entities=entities,
            user_id="benchmark/locomo/run/conv-42",
        )

        assert plan.subject_scope == "multi"
        assert [candidate.entity_id for candidate in plan.subject_candidates] == [
            "person:nate",
            "person:joanna",
        ]
        assert plan.object_candidates == []

    def test_role_aware_between_people_binds_subject_and_object_mentions(self):
        conditions = L2Conditions(
            content_query="What does Melanie think about Caroline?",
            subject_hint="explicit",
            predicate_family="relationship",
            semantic_frame=L2SemanticFrame(
                query_family="relationship",
                subject_scope="explicit",
                subject_mode="single",
                relation_shape="between_people",
                subject_mentions=["Melanie"],
                object_mentions=["Caroline"],
                entity_mentions=["Caroline", "Melanie"],
                answer_kind="topic",
            ),
        )
        entities = [
            {
                "entity_id": "person:caroline",
                "entity_type": "person",
                "canonical_name": "Caroline",
                "confidence": 0.95,
                "match_source": "exact",
            },
            {
                "entity_id": "person:melanie",
                "entity_type": "person",
                "canonical_name": "Melanie",
                "confidence": 0.95,
                "match_source": "exact",
            },
        ]

        plan = build_grounding_plan(
            conditions,
            resolved_entities=entities,
            user_id="benchmark/locomo/run/conv-26",
        )

        assert [candidate.entity_id for candidate in plan.subject_candidates] == ["person:melanie"]
        assert [candidate.entity_id for candidate in plan.object_candidates] == ["person:caroline"]

    def test_self_query_with_non_person_target_still_binds_user_subject(self):
        conditions = L2Conditions(
            content_query="Do I like Bilibili?",
            subject_hint="self",
            predicate_family="preference",
        )
        entities = [
            {
                "entity_id": "software:bilibili",
                "entity_type": "software",
                "canonical_name": "Bilibili",
                "confidence": 0.95,
                "match_source": "alias",
            },
        ]
        plan = build_grounding_plan(
            conditions,
            resolved_entities=entities,
            user_id="u1",
        )
        assert [candidate.entity_id for candidate in plan.subject_candidates] == ["user:u1"]
        assert [candidate.entity_id for candidate in plan.object_candidates] == ["software:bilibili"]

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


def test_build_grounding_plan_copies_allow_soft_edges():
    conditions = L2Conditions(content_query="x", allow_soft_edges=True)
    plan = build_grounding_plan(conditions, resolved_entities=[], user_id="u1")
    assert plan.allow_soft_edges is True

    conditions2 = L2Conditions(content_query="x", allow_soft_edges=False)
    plan2 = build_grounding_plan(conditions2, resolved_entities=[], user_id="u1")
    assert plan2.allow_soft_edges is False


def test_build_grounding_plan_copies_hop2_target_type():
    plan = build_grounding_plan(L2Conditions(content_query="x", hop2_target_type="media"),
                                resolved_entities=[], user_id="u1")
    assert plan.hop2_target_type == "media"
    plan2 = build_grounding_plan(L2Conditions(content_query="x"),
                                 resolved_entities=[], user_id="u1")
    assert plan2.hop2_target_type is None
