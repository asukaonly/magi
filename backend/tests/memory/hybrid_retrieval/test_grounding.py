"""Tests for L2 query grounding."""


import pytest

from magi.memory.hybrid_retrieval.grounding import (
    build_grounding_plan,
)
from magi.memory.hybrid_retrieval.models import (
    L2Conditions,
    L2SemanticFrame,
    SemanticConstraint,
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

    @pytest.mark.parametrize("explicit_kind,expected", [(None, "creator"), ("place", "place")])
    def test_explicit_predicates_drive_inferred_answer_kind_unless_frame_overrides(
        self, explicit_kind, expected
    ):
        conditions = L2Conditions(
            content_query="test",
            predicates=["LIKES", "DISLIKES"],
            semantic_frame=(
                None
                if explicit_kind is None
                else L2SemanticFrame(query_family="affinity", subject_scope="self", answer_kind=explicit_kind)
            ),
        )
        plan = build_grounding_plan(conditions, resolved_entities=[], user_id="u1")
        assert [candidate.predicate for candidate in plan.predicate_candidates] == ["LIKES", "DISLIKES"]
        assert set(plan.expanded_predicates) == {"LIKES", "DISLIKES", "INTERESTED_IN"}
        assert plan.answer_kind == expected


    def test_temporal_context_from_time_range(self):
        conditions = L2Conditions(content_query="test")
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="u1",
            time_range=TimeRange(start=100.0, end=200.0),
        )
        assert plan.temporal_context.mode == "during"
        assert (plan.temporal_context.start, plan.temporal_context.end) == (100.0, 200.0)

    def test_untyped_catalog_mentions_do_not_become_hard_object_constraints(self):
        conditions = L2Conditions(content_query="test")
        entities = [
            {"entity_id": "e1", "entity_type": "software", "canonical_name": "VS Code", "confidence": 0.9},
        ]
        plan = build_grounding_plan(
            conditions,
            resolved_entities=entities,
            user_id="u1",
        )
        assert plan.object_candidates == []

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


    @pytest.mark.parametrize("typed,reverse", [(False, False), (True, False), (True, True)])
    def test_role_aware_shared_fact_binds_all_subject_mentions(self, typed, reverse):
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

        if not typed:
            conditions.semantic_frame.subject_mode = "none"
            conditions.semantic_frame.relation_shape = "unknown"
        if reverse:
            entities.reverse()
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

    @pytest.mark.parametrize("typed,reverse", [(False, False), (True, False), (True, True)])
    def test_role_aware_between_people_binds_subject_and_object_mentions(self, typed, reverse):
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

        if not typed:
            conditions.semantic_frame.query_family = "profile"
            conditions.semantic_frame.subject_mode = "none"
            conditions.semantic_frame.relation_shape = "unknown"
        if reverse:
            entities.reverse()
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
            semantic_frame=L2SemanticFrame(query_family="affinity", answer_kind="topic", subject_scope="self", object_mentions=["Bilibili"]),
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
        assert [(c.field, c.operator, c.value, c.scope) for c in plan.object_constraints] == [
            ("object_type", "in", "software", "target")
        ]

    def test_semantic_constraint_forwarded(self):
        conditions = L2Conditions(
            content_query="test",
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="creator",
                answer_unit="identity",
                constraints=[
                    SemanticConstraint(
                        scope="target",
                        facet="platform",
                        raw_value="YouTube",
                        resolved_entity_id="software:youtube",
                    )
                ],
            ),
        )
        plan = build_grounding_plan(
            conditions,
            resolved_entities=[],
            user_id="u1",
        )
        assert [
            (c.field, c.operator, c.value, c.scope)
            for c in plan.object_constraints
            if c.field == "platform"
        ] == [("platform", "eq", "software:youtube", "target")]
