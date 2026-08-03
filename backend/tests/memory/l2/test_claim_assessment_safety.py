"""Safety tests for host-validated Claim conflict assessments."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.memory.l2.graph_conflicts import GraphConflictRule, build_graph_conflict_matrix
from magi.memory.l2.models import (
    ContradictionHint,
    L2ConflictArbitrationResult,
    L2Phase1FactClaim,
    L2Phase1Result,
    L2Phase2ClaimAssessment,
)
from magi.memory.l2.pipeline.conflict import L2ConflictArbitrationMixin
from magi.memory.l2.pipeline.extraction_contracts import (
    _Phase1ExtractionFlow,
    _Phase2CandidateSet,
)
from magi.memory.l2.pipeline.phase2_flow import L2Phase2FlowMixin
from magi.memory.l2.pipeline.validation.claim_assessments import (
    AssessmentActionEligibility,
    AssessmentCandidateScope,
    L2ClaimAssessmentValidationMixin,
    ValidatedClaimAssessment,
)
from magi.memory.l2.semantic_routing import SemanticRouteInput, derive_semantic_route


class _DecisionHarness(L2Phase2FlowMixin, L2ConflictArbitrationMixin):
    pass


def _claim(
    *,
    claim_id: str = "claim:new",
    predicate: str = "LIKES",
    object_ref: str = "topic:jazz",
    object_type: str = "topic",
    confidence: float = 0.95,
    evidence_event_ids: list[str] | None = None,
) -> L2Phase1FactClaim:
    return L2Phase1FactClaim(
        claim_id=claim_id,
        subject_ref="user:u1",
        subject_type="user",
        predicate=predicate,
        object_ref=object_ref,
        object_type=object_type,
        fact_kind="stable_preference" if predicate in {"LIKES", "DISLIKES"} else "explicit_fact",
        confidence=confidence,
        evidence_text=f"evidence for {predicate} {object_ref}",
        supporting_event_ids=evidence_event_ids or ["evt-new"],
    )


def _graph_candidate(claim: L2Phase1FactClaim) -> dict[str, Any]:
    return {
        "_claim_id": claim.claim_id,
        "subject_id": "user:u1",
        "subject_type": "user",
        "predicate": claim.predicate,
        "object_id": claim.object_ref,
        "object_type": claim.object_type,
        "evidence_event_ids": list(claim.supporting_event_ids),
        "confidence": claim.confidence,
    }


def _assertion_route(claim: L2Phase1FactClaim):
    return derive_semantic_route(
        SemanticRouteInput(
            claim_id=claim.claim_id,
            subject_id="user:u1",
            subject_type="user",
            canonical_predicate=claim.predicate,
            fact_kind=claim.fact_kind,
            object_type=claim.object_type,
            object_value=claim.object_ref,
            object_entity_id=claim.object_ref,
            temporal_cue="stable",
            specificity="concrete",
            target_from=None,
            target_to=None,
            raw_time_expression="",
            time_resolution="unscheduled",
        )
    )


def _assertion_candidate(
    claim: L2Phase1FactClaim,
    *,
    slot_key: str,
    trait_value: str = "like",
) -> dict[str, Any]:
    return {
        "supporting_claim_ids": [claim.claim_id],
        "semantic_route_slot_key": slot_key,
        "trait_value": trait_value,
    }


def _assertion_record(
    route: Any,
    *,
    assertion_id: str = "assert:old",
    trait_value: str = "dislike",
    slot_key: str | None = None,
) -> dict[str, Any]:
    return {
        "assertion_id": assertion_id,
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": route.family,
        "trait_name": route.trait_code,
        "trait_value": trait_value,
        "target_entity_id": route.target_entity_id,
        "target_entity_type": route.target_entity_type,
        "slot_key": slot_key or route.slot_key,
        "scope_key": "global",
        "evidence_events": ["evt-old"],
    }


def _validate_graph_assessment(
    *,
    claim: L2Phase1FactClaim,
    record: dict[str, Any],
    relationship: str = "contradicts",
    rules: list[GraphConflictRule] | None = None,
    arbitration_min_confidence: float = 0.85,
) -> tuple[ValidatedClaimAssessment, int]:
    validated, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        semantic_routes={},
        graph_candidates=[_graph_candidate(claim)],
        assertion_candidates=[],
        assessments=[
            L2Phase2ClaimAssessment(
                claim_id=claim.claim_id,
                relationship=relationship,
                related_record_id=str(record["triple_id"]),
            )
        ],
        existing_graph_edges=[record],
        existing_assertions=[],
        graph_conflict_rules=rules or [],
        arbitration_min_confidence=arbitration_min_confidence,
    )
    assert len(validated) == 1
    return validated[0], rejected


@pytest.mark.parametrize(
    ("new_event_ids", "expected_action", "expected_independent"),
    [
        (["evt-old"], AssessmentActionEligibility.NOOP, False),
        (["evt-new"], AssessmentActionEligibility.REVALIDATE, True),
    ],
)
def test_same_relationship_value_requires_independent_evidence_to_revalidate(
    new_event_ids: list[str],
    expected_action: AssessmentActionEligibility,
    expected_independent: bool,
) -> None:
    claim = _claim(evidence_event_ids=new_event_ids)
    assessment, rejected = _validate_graph_assessment(
        claim=claim,
        record={
            "triple_id": "triple:old",
            "subject_id": "user:u1",
            "predicate": "LIKES",
            "object_id": "topic:jazz",
            "scope_key": "global",
            "evidence_event_ids": ["evt-old"],
        },
    )

    assert rejected == 0
    assert assessment.same_value is True
    assert assessment.independent_evidence is expected_independent
    assert assessment.action_eligibility is expected_action
    if expected_action is AssessmentActionEligibility.REVALIDATE:
        assert assessment.hint is not None
        assert assessment.hint.recommended_action == "revalidate_only"
    else:
        assert assessment.hint is None


def test_relationship_conflict_requires_same_object_opposite_rule() -> None:
    rules = list(build_graph_conflict_matrix().values())
    claim = _claim(predicate="DISLIKES", object_ref="topic:jazz")
    same_object, rejected = _validate_graph_assessment(
        claim=claim,
        record={
            "triple_id": "triple:like-jazz",
            "subject_id": "user:u1",
            "predicate": "LIKES",
            "object_id": "topic:jazz",
            "scope_key": "global",
            "evidence_event_ids": ["evt-old"],
        },
        rules=rules,
    )
    cross_object, cross_rejected = _validate_graph_assessment(
        claim=claim,
        record={
            "triple_id": "triple:like-cilantro",
            "subject_id": "user:u1",
            "predicate": "LIKES",
            "object_id": "food:cilantro",
            "scope_key": "global",
            "evidence_event_ids": ["evt-old"],
        },
        rules=rules,
    )

    assert rejected == 0
    assert same_object.compatibility == "relationship_opposite"
    assert same_object.action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION
    assert same_object.hint is not None
    assert same_object.hint.contradiction_kind == "preference_reversal"
    assert cross_rejected == 1
    assert cross_object.action_eligibility is AssessmentActionEligibility.REJECTED
    assert cross_object.reason_code == "assessment_rejected_no_relationship_taxonomy"
    assert cross_object.hint is None


def test_lives_in_change_needs_explicit_exclusive_rule() -> None:
    claim = _claim(
        predicate="LIVES_IN",
        object_ref="place:shanghai",
        object_type="place",
    )
    record = {
        "triple_id": "triple:hangzhou",
        "subject_id": "user:u1",
        "predicate": "LIVES_IN",
        "object_id": "place:hangzhou",
        "scope_key": "global",
        "evidence_event_ids": ["evt-old"],
    }

    without_rule, rejected = _validate_graph_assessment(claim=claim, record=record)
    with_rule, explicit_rejected = _validate_graph_assessment(
        claim=claim,
        record=record,
        relationship="evolves",
        rules=[
            GraphConflictRule(
                predicate="LIVES_IN",
                exclusive_group="current_residence",
            )
        ],
    )

    assert rejected == 1
    assert without_rule.action_eligibility is AssessmentActionEligibility.REJECTED
    assert without_rule.reason_code == "assessment_rejected_no_relationship_taxonomy"
    assert explicit_rejected == 0
    assert with_rule.compatibility == "relationship_exclusive_group"
    assert with_rule.action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION


def test_low_confidence_different_value_is_quarantined_without_hint() -> None:
    rules = list(build_graph_conflict_matrix().values())
    assessment, rejected = _validate_graph_assessment(
        claim=_claim(predicate="DISLIKES", confidence=0.4),
        record={
            "triple_id": "triple:old",
            "subject_id": "user:u1",
            "predicate": "LIKES",
            "object_id": "topic:jazz",
            "scope_key": "global",
            "evidence_event_ids": ["evt-old"],
        },
        rules=rules,
        arbitration_min_confidence=0.85,
    )

    assert rejected == 0
    assert assessment.action_eligibility is AssessmentActionEligibility.QUARANTINED
    assert assessment.reason_code == "assessment_low_confidence_quarantined"
    assert assessment.hint is None


def test_assertion_compatibility_uses_host_route_target_scope_and_typed_value() -> None:
    claim = _claim(predicate="LIKES", object_ref="topic:jazz")
    route = derive_semantic_route(
        SemanticRouteInput(
            claim_id=claim.claim_id,
            subject_id="user:u1",
            subject_type="user",
            canonical_predicate="LIKES",
            fact_kind="stable_preference",
            object_type="topic",
            object_value="topic:jazz",
            object_entity_id="topic:jazz",
            temporal_cue="stable",
            specificity="concrete",
            target_from=None,
            target_to=None,
            raw_time_expression="",
            time_resolution="unscheduled",
        )
    )
    record = {
        "assertion_id": "assert:old",
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": route.family,
        "trait_name": route.trait_code,
        "trait_value": "dislike",
        "target_entity_id": "topic:jazz",
        "target_entity_type": "topic",
        "slot_key": route.slot_key,
        "scope_key": "global",
        "evidence_events": ["evt-old"],
    }
    validated, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        semantic_routes={claim.claim_id: route},
        graph_candidates=[_graph_candidate(claim)],
        assertion_candidates=[
            {
                "supporting_claim_ids": [claim.claim_id],
                "semantic_route_slot_key": route.slot_key,
                "trait_value": "like",
            }
        ],
        assessments=[
            L2Phase2ClaimAssessment(
                claim_id=claim.claim_id,
                relationship="contradicts",
                related_record_id="assert:old",
            )
        ],
        existing_graph_edges=[],
        existing_assertions=[record],
        graph_conflict_rules=[],
        arbitration_min_confidence=0.85,
    )

    assert rejected == 0
    assert validated[0].compatibility == "assertion_same_slot"
    assert validated[0].same_value is False
    assert validated[0].action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION

    record["target_entity_id"] = "topic:classical"
    incompatible, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        semantic_routes={claim.claim_id: route},
        graph_candidates=[_graph_candidate(claim)],
        assertion_candidates=[],
        assessments=[
            L2Phase2ClaimAssessment(
                claim_id=claim.claim_id,
                relationship="contradicts",
                related_record_id="assert:old",
            )
        ],
        existing_graph_edges=[],
        existing_assertions=[record],
        graph_conflict_rules=[],
        arbitration_min_confidence=0.85,
    )
    assert rejected == 1
    assert incompatible[0].action_eligibility is AssessmentActionEligibility.REJECTED
    assert incompatible[0].hint is None


def test_host_synthesizes_assertion_conflict_when_model_omits_assessment() -> None:
    claim = _claim(predicate="LIKES", object_ref="topic:jazz")
    route = _assertion_route(claim)
    record = _assertion_record(route)
    unrelated = _assertion_record(
        route,
        assertion_id="assert:unrelated",
        slot_key="slt_unrelated",
    )

    validated, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        semantic_routes={claim.claim_id: route},
        graph_candidates=[],
        assertion_candidates=[
            _assertion_candidate(claim, slot_key=route.slot_key),
        ],
        assessments=[],
        existing_graph_edges=[],
        existing_assertions=[record, unrelated],
        graph_conflict_rules=[],
        arbitration_min_confidence=0.85,
    )

    assert rejected == 0
    assert len(validated) == 1
    assert validated[0].related_record_id == "assert:old"
    assert validated[0].relationship == "contradicts"
    assert validated[0].compatibility == "assertion_same_slot"
    assert validated[0].action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION
    assert validated[0].candidate_scope == AssessmentCandidateScope((), (0,))
    assert validated[0].hint is not None


@pytest.mark.parametrize(
    ("event_ids", "expected_action"),
    [
        (["evt-old"], AssessmentActionEligibility.NOOP),
        (["evt-new"], AssessmentActionEligibility.REVALIDATE),
    ],
)
def test_host_synthesized_same_value_assertion_only_noops_or_revalidates(
    event_ids: list[str],
    expected_action: AssessmentActionEligibility,
) -> None:
    claim = _claim(
        predicate="LIKES",
        object_ref="topic:jazz",
        evidence_event_ids=event_ids,
    )
    route = _assertion_route(claim)

    validated, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        semantic_routes={claim.claim_id: route},
        graph_candidates=[],
        assertion_candidates=[
            _assertion_candidate(claim, slot_key=route.slot_key),
        ],
        assessments=[],
        existing_graph_edges=[],
        existing_assertions=[
            _assertion_record(route, trait_value="like"),
        ],
        graph_conflict_rules=[],
        arbitration_min_confidence=0.85,
    )

    assert rejected == 0
    assert len(validated) == 1
    assert validated[0].relationship == "refines"
    assert validated[0].same_value is True
    assert validated[0].action_eligibility is expected_action
    assert validated[0].action_eligibility not in {
        AssessmentActionEligibility.PENDING_ARBITRATION,
        AssessmentActionEligibility.QUARANTINED,
    }


def test_model_refines_cannot_mask_assertion_value_conflict() -> None:
    claim = _claim(predicate="LIKES", object_ref="topic:jazz")
    route = _assertion_route(claim)
    record = _assertion_record(route)

    validated, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        semantic_routes={claim.claim_id: route},
        graph_candidates=[],
        assertion_candidates=[
            _assertion_candidate(claim, slot_key=route.slot_key),
        ],
        assessments=[
            L2Phase2ClaimAssessment(
                claim_id=claim.claim_id,
                relationship="refines",
                related_record_id="assert:old",
            )
        ],
        existing_graph_edges=[],
        existing_assertions=[record],
        graph_conflict_rules=[],
        arbitration_min_confidence=0.85,
    )

    assert rejected == 0
    assert len(validated) == 1
    assert validated[0].relationship == "refines"
    assert validated[0].compatibility == "assertion_same_slot"
    assert validated[0].action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION
    assert validated[0].reason_code == "assessment_pending_arbitration"
    assert validated[0].hint is not None


def test_host_synthesizes_graph_conflict_when_model_omits_assessment() -> None:
    claim = _claim(predicate="DISLIKES", object_ref="topic:jazz")
    validated, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        semantic_routes={},
        graph_candidates=[_graph_candidate(claim)],
        assertion_candidates=[],
        assessments=[],
        existing_graph_edges=[
            {
                "triple_id": "triple:like-jazz",
                "subject_id": "user:u1",
                "predicate": "LIKES",
                "object_id": "topic:jazz",
                "scope_key": "global",
                "evidence_event_ids": ["evt-old"],
            }
        ],
        existing_assertions=[],
        graph_conflict_rules=list(build_graph_conflict_matrix().values()),
        arbitration_min_confidence=0.85,
    )

    assert rejected == 0
    assert len(validated) == 1
    assert validated[0].related_record_id == "triple:like-jazz"
    assert validated[0].relationship == "contradicts"
    assert validated[0].compatibility == "relationship_opposite"
    assert validated[0].action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION
    assert validated[0].candidate_scope == AssessmentCandidateScope((0,), ())


def test_refines_is_host_validated_and_unknown_record_is_rejected() -> None:
    claim = _claim()
    record = {
        "triple_id": "triple:old",
        "subject_id": "user:u1",
        "predicate": "LIKES",
        "object_id": "topic:jazz",
        "scope_key": "global",
        "evidence_event_ids": ["evt-new"],
    }
    refined, rejected = _validate_graph_assessment(
        claim=claim,
        record=record,
        relationship="refines",
    )
    (
        unknown,
        unknown_rejected,
    ) = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        semantic_routes={},
        graph_candidates=[_graph_candidate(claim)],
        assertion_candidates=[],
        assessments=[
            L2Phase2ClaimAssessment(
                claim_id=claim.claim_id,
                relationship="contradicts",
                related_record_id="triple:missing",
            )
        ],
        existing_graph_edges=[],
        existing_assertions=[],
        graph_conflict_rules=[],
        arbitration_min_confidence=0.85,
    )

    assert rejected == 0
    assert refined.action_eligibility is AssessmentActionEligibility.NOOP
    assert refined.reason_code == "assessment_duplicate_evidence_noop"
    assert refined.hint is None
    assert unknown_rejected == 1
    assert unknown[0].action_eligibility is AssessmentActionEligibility.REJECTED


def _pending_assessment(claim_id: str, target_id: str) -> ValidatedClaimAssessment:
    return ValidatedClaimAssessment(
        claim_id=claim_id,
        relationship="evolves",
        related_record_id=target_id,
        target_record_type="knowledge_graph",
        compatibility="relationship_exclusive_group",
        same_value=False,
        independent_evidence=True,
        candidate_scope=AssessmentCandidateScope((0,), ()),
        action_eligibility=AssessmentActionEligibility.PENDING_ARBITRATION,
        reason_code="assessment_pending_arbitration",
        confidence=0.95,
        target_slot_key=f"slot:{target_id}",
        hint=ContradictionHint(
            target_record_id=target_id,
            target_record_type="knowledge_graph",
            contradiction_kind="state_reversal",
            confidence=0.95,
            evidence_text="new evidence",
            recommended_action="pending_arbitration",
        ),
    )


def _candidate_set(
    assessments: list[ValidatedClaimAssessment],
) -> _Phase2CandidateSet:
    return _Phase2CandidateSet(
        graph_candidates=[
            {"_claim_id": "claim:a", "subject_id": "user:u1", "predicate": "A", "object_id": "a"},
            {"_claim_id": "claim:b", "subject_id": "user:u1", "predicate": "B", "object_id": "b"},
            {
                "_claim_id": "claim:unrelated",
                "subject_id": "user:u1",
                "predicate": "U",
                "object_id": "u",
            },
        ],
        facet_candidates=[],
        assertion_candidates=[
            {
                "supporting_claim_ids": ["claim:unrelated"],
                "semantic_route_slot_key": "slot:unrelated",
            }
        ],
        contradiction_hints=[
            assessment.hint for assessment in assessments if assessment.hint is not None
        ],
        validated_claim_assessments=assessments,
        rejected_graph_candidate_count=0,
        rejected_assertion_candidate_count=0,
        claim_assessment_count=len(assessments),
        rejected_claim_assessment_count=0,
    )


def _phase1_flow() -> _Phase1ExtractionFlow:
    return _Phase1ExtractionFlow(
        phase1_result=L2Phase1Result(),
        resolved_mentions=[],
        profile_signal_object_refs=set(),
        semantic_routes={},
        claim_outcomes=[],
    )


def _batch() -> SimpleNamespace:
    return SimpleNamespace(stored_event=SimpleNamespace(event_id="evt-new"))


def test_keep_existing_removes_only_conflicting_claim_candidates() -> None:
    assessments = [_pending_assessment("claim:a", "triple:a")]
    candidates = _candidate_set(assessments)
    phase1_flow = _phase1_flow()

    _DecisionHarness()._apply_phase2_arbitration_decision(
        _batch(),
        phase1_flow,
        candidates,
        L2ConflictArbitrationResult(
            decision="keep_existing",
            winning_record_ids=["triple:a"],
        ),
    )

    assert [candidate["_claim_id"] for candidate in candidates.graph_candidates] == [
        "claim:b",
        "claim:unrelated",
    ]
    assert candidates.assertion_candidates[0]["supporting_claim_ids"] == ["claim:unrelated"]
    assert candidates.contradiction_hints == []
    assessment_outcomes = [
        outcome for outcome in phase1_flow.claim_outcomes if outcome.target_kind == "assessment"
    ]
    assert [(outcome.outcome, outcome.reason_code) for outcome in assessment_outcomes] == [
        ("noop", "conflict_keep_existing")
    ]
    assert assessment_outcomes[0].target_id
    assert not any(
        hint.recommended_action == "revalidate_only" for hint in candidates.contradiction_hints
    )


def test_no_arbitration_quarantines_conflict_and_preserves_unrelated_candidates() -> None:
    assessments = [_pending_assessment("claim:a", "triple:a")]
    candidates = _candidate_set(assessments)
    phase1_flow = _phase1_flow()

    _DecisionHarness()._apply_phase2_arbitration_decision(
        _batch(),
        phase1_flow,
        candidates,
        None,
    )

    assert [candidate["_claim_id"] for candidate in candidates.graph_candidates] == [
        "claim:b",
        "claim:unrelated",
    ]
    assert candidates.assertion_candidates
    assert candidates.contradiction_hints == []
    assert any(
        outcome.target_kind == "assessment"
        and outcome.outcome == "quarantined"
        and outcome.reason_code == "conflict_arbitration_unavailable"
        for outcome in phase1_flow.claim_outcomes
    )


@pytest.mark.parametrize("decision", ["keep_new", "mark_evolution"])
def test_new_value_decisions_only_select_explicit_targets(decision: str) -> None:
    assessments = [
        _pending_assessment("claim:a", "triple:a"),
        _pending_assessment("claim:b", "triple:b"),
    ]
    candidates = _candidate_set(assessments)
    phase1_flow = _phase1_flow()

    _DecisionHarness()._apply_phase2_arbitration_decision(
        _batch(),
        phase1_flow,
        candidates,
        L2ConflictArbitrationResult(
            decision=decision,
            superseded_record_ids=["triple:a"],
        ),
    )

    assert [candidate["_claim_id"] for candidate in candidates.graph_candidates] == [
        "claim:a",
        "claim:unrelated",
    ]
    assessment_outcomes = {
        outcome.claim_id: (outcome.outcome, outcome.reason_code)
        for outcome in phase1_flow.claim_outcomes
        if outcome.target_kind == "assessment"
    }
    assert assessment_outcomes["claim:a"] == ("accepted", f"conflict_{decision}")
    assert assessment_outcomes["claim:b"] == (
        "quarantined",
        "conflict_arbitration_unselected",
    )
    if decision == "mark_evolution":
        assert [hint.target_record_id for hint in candidates.contradiction_hints] == ["triple:a"]
        assert candidates.contradiction_hints[0].recommended_action == "mark_deprecated"
    else:
        assert candidates.contradiction_hints == []


def test_partial_target_selection_quarantines_the_whole_claim() -> None:
    assessments = [
        _pending_assessment("claim:a", "triple:a"),
        _pending_assessment("claim:a", "triple:a-secondary"),
    ]
    candidates = _candidate_set(assessments)
    phase1_flow = _phase1_flow()

    _DecisionHarness()._apply_phase2_arbitration_decision(
        _batch(),
        phase1_flow,
        candidates,
        L2ConflictArbitrationResult(
            decision="mark_evolution",
            superseded_record_ids=["triple:a"],
        ),
    )

    assert [candidate["_claim_id"] for candidate in candidates.graph_candidates] == [
        "claim:b",
        "claim:unrelated",
    ]
    assert candidates.contradiction_hints == []
    assessment_outcomes = [
        (outcome.outcome, outcome.reason_code)
        for outcome in phase1_flow.claim_outcomes
        if outcome.target_kind == "assessment"
    ]
    assert assessment_outcomes == [
        ("quarantined", "conflict_arbitration_unselected"),
        ("quarantined", "conflict_arbitration_unselected"),
    ]


@pytest.mark.asyncio
async def test_store_rejects_unknown_contradiction_action_without_mutation(
    l2_store_with_schema,
) -> None:
    triple_id = await l2_store_with_schema.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="topic:jazz",
        object_type="topic",
        evidence_event_ids=["evt-old"],
        confidence=0.9,
        observed_at=1_710_000_000.0,
        source_type="chat",
    )
    before = await l2_store_with_schema.get_relationship(triple_id=triple_id)

    applied = await l2_store_with_schema.apply_contradiction_hint(
        {
            "target_record_type": "knowledge_graph",
            "target_record_id": triple_id,
            "recommended_action": "pending_arbitration",
            "confidence": 0.99,
        }
    )
    after = await l2_store_with_schema.get_relationship(triple_id=triple_id)

    assert applied is False
    assert after["status"] == before["status"] == "active"
    assert after["last_confirmed_at"] == before["last_confirmed_at"]
    assert after["updated_at"] == before["updated_at"]
