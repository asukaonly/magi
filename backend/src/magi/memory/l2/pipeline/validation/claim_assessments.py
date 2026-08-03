"""Host validation of Phase 2 claim-to-record assessments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from ...corrections.fingerprints import (
    canonical_claim_value,
    relationship_slot_key,
    scope_key,
)
from ...graph_conflicts import (
    GraphConflictRule,
    relationship_predicate_slot,
)
from ...models import (
    ContradictionHint,
    L2Phase1FactClaim,
    L2Phase1Result,
    L2Phase2ClaimAssessment,
)
from ...semantic_routing import SemanticRouteDecision

_ALLOWED_RELATIONSHIPS = frozenset({"refines", "contradicts", "evolves"})
_PREFERENCE_OPPOSITES = frozenset({"LIKES", "DISLIKES"})


class AssessmentActionEligibility(str, Enum):
    """Host-owned action state for one untrusted Phase 2 assessment."""

    REVALIDATE = "revalidate"
    PENDING_ARBITRATION = "pending_arbitration"
    NOOP = "noop"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class AssessmentCandidateScope:
    """Exact batch candidates associated with one Claim assessment."""

    graph_candidate_indexes: tuple[int, ...]
    assertion_candidate_indexes: tuple[int, ...]

    @property
    def has_candidates(self) -> bool:
        return bool(self.graph_candidate_indexes or self.assertion_candidate_indexes)


@dataclass(frozen=True, slots=True)
class ValidatedClaimAssessment:
    """Host-validated assessment kept separate from executable side effects."""

    claim_id: str
    relationship: str
    related_record_id: str
    target_record_type: str
    compatibility: str
    same_value: bool
    independent_evidence: bool
    candidate_scope: AssessmentCandidateScope
    action_eligibility: AssessmentActionEligibility
    reason_code: str
    confidence: float
    target_slot_key: str | None = None
    hint: ContradictionHint | None = None

    @property
    def target_id(self) -> str:
        """Return the stable Claim outcome target for this assessment."""

        record_type = self.target_record_type or "unknown_record"
        record_id = self.related_record_id or "missing"
        relationship = self.relationship or "invalid"
        return f"assessment:{record_type}:{record_id}:{relationship}"

    @property
    def is_pending_conflict(self) -> bool:
        return self.action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION


@dataclass(frozen=True, slots=True)
class _CompatibilityResult:
    compatibility: str
    same_value: bool
    independent_evidence: bool
    target_slot_key: str | None
    contradiction_kind: str | None
    reason_code: str


class L2ClaimAssessmentValidationMixin:
    """Accept only assessments whose compatibility is recomputed by the host."""

    def _validate_phase2_claim_assessments(
        self,
        *,
        phase1_result: L2Phase1Result,
        semantic_routes: Mapping[str, SemanticRouteDecision],
        graph_candidates: list[dict[str, Any]],
        assertion_candidates: list[dict[str, Any]],
        assessments: list[L2Phase2ClaimAssessment],
        existing_graph_edges: list[dict[str, Any]],
        existing_assertions: list[dict[str, Any]],
        graph_conflict_rules: Iterable[GraphConflictRule | Mapping[str, Any]],
        arbitration_min_confidence: float,
    ) -> tuple[list[ValidatedClaimAssessment], int]:
        claims_by_id = {
            claim.claim_id: claim
            for claim in phase1_result.fact_claims
            if str(claim.claim_id or "").strip()
        }
        records_by_id = _existing_records_by_id(existing_graph_edges, existing_assertions)
        rules = _graph_rules_by_predicate(graph_conflict_rules)
        validated: list[ValidatedClaimAssessment] = []
        rejected_count = 0
        for assessment in assessments:
            claim = claims_by_id.get(assessment.claim_id)
            if claim is None:
                rejected_count += 1
                continue
            candidate_scope = _candidate_scope(
                claim.claim_id,
                graph_candidates=graph_candidates,
                assertion_candidates=assertion_candidates,
            )
            record = records_by_id.get(assessment.related_record_id)
            if record is None or assessment.relationship not in _ALLOWED_RELATIONSHIPS:
                rejected_count += 1
                validated.append(
                    _rejected_assessment(
                        claim=claim,
                        assessment=assessment,
                        candidate_scope=candidate_scope,
                        target_record_type=(record[0] if record is not None else "unknown_record"),
                        reason_code=(
                            "assessment_rejected_relationship"
                            if assessment.relationship not in _ALLOWED_RELATIONSHIPS
                            else "assessment_rejected_unknown_record"
                        ),
                    )
                )
                continue
            record_type, record_payload = record
            if assessment.relationship == "refines":
                validated.append(
                    ValidatedClaimAssessment(
                        claim_id=claim.claim_id,
                        relationship=assessment.relationship,
                        related_record_id=assessment.related_record_id,
                        target_record_type=record_type,
                        compatibility="refines_without_taxonomy",
                        same_value=False,
                        independent_evidence=False,
                        candidate_scope=candidate_scope,
                        action_eligibility=AssessmentActionEligibility.NOOP,
                        reason_code="assessment_refines_noop",
                        confidence=_claim_confidence(claim),
                        target_slot_key=_record_slot_key(record_payload),
                    )
                )
                continue

            if record_type == "knowledge_graph":
                compatibility = _relationship_compatibility(
                    claim=claim,
                    record=record_payload,
                    graph_candidates=graph_candidates,
                    graph_rules=rules,
                )
            else:
                compatibility = _assertion_compatibility(
                    claim=claim,
                    record=record_payload,
                    route=semantic_routes.get(claim.claim_id),
                    assertion_candidates=assertion_candidates,
                )
            result = _validated_assessment(
                claim=claim,
                assessment=assessment,
                record_type=record_type,
                candidate_scope=candidate_scope,
                compatibility=compatibility,
                arbitration_min_confidence=arbitration_min_confidence,
            )
            if result.action_eligibility is AssessmentActionEligibility.REJECTED:
                rejected_count += 1
            validated.append(result)
        return validated, rejected_count


def _validated_assessment(
    *,
    claim: L2Phase1FactClaim,
    assessment: L2Phase2ClaimAssessment,
    record_type: str,
    candidate_scope: AssessmentCandidateScope,
    compatibility: _CompatibilityResult,
    arbitration_min_confidence: float,
) -> ValidatedClaimAssessment:
    confidence = _claim_confidence(claim)
    action = AssessmentActionEligibility.REJECTED
    hint: ContradictionHint | None = None
    reason_code = compatibility.reason_code
    if compatibility.same_value:
        if compatibility.independent_evidence:
            action = AssessmentActionEligibility.REVALIDATE
            reason_code = "assessment_same_value_independent_evidence"
            hint = _assessment_hint(
                claim=claim,
                record_type=record_type,
                record_id=assessment.related_record_id,
                contradiction_kind="corroboration",
                action="revalidate_only",
            )
        else:
            action = AssessmentActionEligibility.NOOP
            reason_code = "assessment_duplicate_evidence_noop"
    elif compatibility.contradiction_kind is not None:
        if not candidate_scope.has_candidates:
            action = AssessmentActionEligibility.REJECTED
            reason_code = "assessment_rejected_missing_candidate"
        elif confidence < max(0.0, min(1.0, float(arbitration_min_confidence))):
            action = AssessmentActionEligibility.QUARANTINED
            reason_code = "assessment_low_confidence_quarantined"
        else:
            action = AssessmentActionEligibility.PENDING_ARBITRATION
            reason_code = "assessment_pending_arbitration"
            hint = _assessment_hint(
                claim=claim,
                record_type=record_type,
                record_id=assessment.related_record_id,
                contradiction_kind=compatibility.contradiction_kind,
                action="pending_arbitration",
            )
    return ValidatedClaimAssessment(
        claim_id=claim.claim_id,
        relationship=assessment.relationship,
        related_record_id=assessment.related_record_id,
        target_record_type=record_type,
        compatibility=compatibility.compatibility,
        same_value=compatibility.same_value,
        independent_evidence=compatibility.independent_evidence,
        candidate_scope=candidate_scope,
        action_eligibility=action,
        reason_code=reason_code,
        confidence=confidence,
        target_slot_key=compatibility.target_slot_key,
        hint=hint,
    )


def _rejected_assessment(
    *,
    claim: L2Phase1FactClaim,
    assessment: L2Phase2ClaimAssessment,
    candidate_scope: AssessmentCandidateScope,
    target_record_type: str,
    reason_code: str,
) -> ValidatedClaimAssessment:
    return ValidatedClaimAssessment(
        claim_id=claim.claim_id,
        relationship=assessment.relationship,
        related_record_id=assessment.related_record_id,
        target_record_type=target_record_type,
        compatibility="invalid",
        same_value=False,
        independent_evidence=False,
        candidate_scope=candidate_scope,
        action_eligibility=AssessmentActionEligibility.REJECTED,
        reason_code=reason_code,
        confidence=_claim_confidence(claim),
    )


def _assertion_compatibility(
    *,
    claim: L2Phase1FactClaim,
    record: dict[str, Any],
    route: SemanticRouteDecision | None,
    assertion_candidates: list[dict[str, Any]],
) -> _CompatibilityResult:
    if route is None or not route.can_project_assertion:
        return _incompatible("assessment_rejected_missing_assertion_route")
    record_slot_key = _record_slot_key(record)
    identity_matches = bool(
        record_slot_key
        and record_slot_key == route.slot_key
        and _text(record.get("entity_id")) == _text(route.subject_id)
        and _text(record.get("entity_type")).casefold() == _text(route.subject_type).casefold()
        and _text(record.get("trait_family")).casefold() == _text(route.family).casefold()
        and _text(record.get("trait_name")).casefold() == _text(route.trait_code).casefold()
        and _text(record.get("target_entity_id")) == _text(route.target_entity_id)
        and _text(record.get("target_entity_type")).casefold()
        == _text(route.target_entity_type).casefold()
        and _text(record.get("scope_key") or "global") == _text(route.scope_key or "global")
    )
    if not identity_matches:
        return _incompatible("assessment_rejected_incompatible_assertion")
    candidate_value = route.canonical_value
    if candidate_value is None:
        matching_candidates = [
            candidate
            for candidate in assertion_candidates
            if claim.claim_id in _candidate_claim_ids(candidate)
            and _text(candidate.get("semantic_route_slot_key")) == record_slot_key
        ]
        candidate_values = {
            canonical_claim_value(candidate.get("trait_value")) for candidate in matching_candidates
        }
        if len(candidate_values) != 1:
            return _incompatible("assessment_rejected_missing_typed_value")
        candidate_value = next(iter(candidate_values))
    same_value = canonical_claim_value(record.get("trait_value")) == canonical_claim_value(
        candidate_value
    )
    return _CompatibilityResult(
        compatibility="assertion_same_value" if same_value else "assertion_same_slot",
        same_value=same_value,
        independent_evidence=_has_independent_evidence(
            claim.supporting_event_ids,
            _event_ids(record.get("evidence_events")),
        ),
        target_slot_key=record_slot_key,
        contradiction_kind=None if same_value else "state_reversal",
        reason_code=(
            "assessment_assertion_same_value"
            if same_value
            else "assessment_assertion_value_conflict"
        ),
    )


def _relationship_compatibility(
    *,
    claim: L2Phase1FactClaim,
    record: dict[str, Any],
    graph_candidates: list[dict[str, Any]],
    graph_rules: Mapping[str, GraphConflictRule],
) -> _CompatibilityResult:
    matching_candidates = [
        candidate
        for candidate in graph_candidates
        if _text(candidate.get("_claim_id")) == claim.claim_id
    ]
    if len(matching_candidates) != 1:
        return _incompatible("assessment_rejected_missing_graph_candidate")
    candidate = matching_candidates[0]
    new_subject = _text(candidate.get("subject_id"))
    old_subject = _text(record.get("subject_id"))
    new_scope = scope_key(candidate.get("scope"))
    old_scope = _text(record.get("scope_key") or "global")
    if not new_subject or new_subject != old_subject or new_scope != old_scope:
        return _incompatible("assessment_rejected_incompatible_relationship_scope")
    new_predicate = _text(candidate.get("predicate")).upper()
    old_predicate = _text(record.get("predicate")).upper()
    new_object = _text(candidate.get("object_id"))
    old_object = _text(record.get("object_id"))
    target_slot_key = _relationship_target_slot(
        subject_id=new_subject,
        predicate=old_predicate,
        object_id=old_object,
        record=record,
        graph_rules=graph_rules,
    )
    same_value = new_predicate == old_predicate and new_object == old_object
    if same_value:
        return _CompatibilityResult(
            compatibility="relationship_exact_triple",
            same_value=True,
            independent_evidence=_has_independent_evidence(
                claim.supporting_event_ids,
                _event_ids(record.get("evidence_event_ids")),
            ),
            target_slot_key=target_slot_key,
            contradiction_kind=None,
            reason_code="assessment_relationship_same_value",
        )

    new_rule = graph_rules.get(new_predicate)
    old_rule = graph_rules.get(old_predicate)
    opposite = bool(
        new_object == old_object
        and (
            (new_rule is not None and old_predicate in new_rule.opposite_predicates)
            or (old_rule is not None and new_predicate in old_rule.opposite_predicates)
        )
    )
    exclusive = bool(
        new_rule is not None
        and old_rule is not None
        and new_rule.exclusive_group
        and new_rule.exclusive_group == old_rule.exclusive_group
    )
    if not opposite and not exclusive:
        return _incompatible("assessment_rejected_no_relationship_taxonomy")
    contradiction_kind = (
        "preference_reversal"
        if opposite and {new_predicate, old_predicate} == _PREFERENCE_OPPOSITES
        else "direct_negation" if opposite else "state_reversal"
    )
    return _CompatibilityResult(
        compatibility="relationship_opposite" if opposite else "relationship_exclusive_group",
        same_value=False,
        independent_evidence=_has_independent_evidence(
            claim.supporting_event_ids,
            _event_ids(record.get("evidence_event_ids")),
        ),
        target_slot_key=target_slot_key,
        contradiction_kind=contradiction_kind,
        reason_code="assessment_relationship_value_conflict",
    )


def _relationship_target_slot(
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
    record: Mapping[str, Any],
    graph_rules: Mapping[str, GraphConflictRule],
) -> str:
    stored = _record_slot_key(record)
    if stored:
        return stored
    return relationship_slot_key(
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        predicate_slot=relationship_predicate_slot(
            graph_rules,
            predicate=predicate,
            object_id=object_id,
        ),
    )


def _incompatible(reason_code: str) -> _CompatibilityResult:
    return _CompatibilityResult(
        compatibility="incompatible",
        same_value=False,
        independent_evidence=False,
        target_slot_key=None,
        contradiction_kind=None,
        reason_code=reason_code,
    )


def _assessment_hint(
    *,
    claim: L2Phase1FactClaim,
    record_type: str,
    record_id: str,
    contradiction_kind: str,
    action: str,
) -> ContradictionHint:
    return ContradictionHint(
        target_record_id=record_id,
        target_record_type=record_type,
        contradiction_kind=contradiction_kind,
        confidence=_claim_confidence(claim),
        evidence_text=claim.evidence_text,
        recommended_action=action,
    )


def _candidate_scope(
    claim_id: str,
    *,
    graph_candidates: list[dict[str, Any]],
    assertion_candidates: list[dict[str, Any]],
) -> AssessmentCandidateScope:
    return AssessmentCandidateScope(
        graph_candidate_indexes=tuple(
            index
            for index, candidate in enumerate(graph_candidates)
            if _text(candidate.get("_claim_id")) == claim_id
        ),
        assertion_candidate_indexes=tuple(
            index
            for index, candidate in enumerate(assertion_candidates)
            if claim_id in _candidate_claim_ids(candidate)
        ),
    )


def _candidate_claim_ids(candidate: Mapping[str, Any]) -> set[str]:
    return {text for raw in candidate.get("supporting_claim_ids", []) if (text := _text(raw))}


def _existing_records_by_id(
    graph_edges: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
) -> dict[str, tuple[str, dict[str, Any]]]:
    records: dict[str, tuple[str, dict[str, Any]]] = {}
    for edge in graph_edges:
        record_id = _text(edge.get("triple_id"))
        if record_id:
            records[record_id] = ("knowledge_graph", edge)
    for assertion in assertions:
        record_id = _text(assertion.get("assertion_id"))
        if record_id:
            records[record_id] = ("tom_trait_assertion", assertion)
    return records


def _graph_rules_by_predicate(
    rules: Iterable[GraphConflictRule | Mapping[str, Any]],
) -> dict[str, GraphConflictRule]:
    normalized: dict[str, GraphConflictRule] = {}
    for raw_rule in rules:
        rule = (
            raw_rule
            if isinstance(raw_rule, GraphConflictRule)
            else GraphConflictRule.from_mapping(raw_rule)
        )
        normalized[rule.predicate] = rule
    return normalized


def _has_independent_evidence(new_event_ids: Iterable[str], old_event_ids: Iterable[str]) -> bool:
    old = {_text(event_id) for event_id in old_event_ids if _text(event_id)}
    return any(_text(event_id) not in old for event_id in new_event_ids if _text(event_id))


def _event_ids(value: Any) -> list[str]:
    raw = value
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            decoded = []
        raw = decoded if isinstance(decoded, list) else []
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [_text(event_id) for event_id in raw if _text(event_id)]


def _record_slot_key(record: Mapping[str, Any]) -> str | None:
    return _text(record.get("slot_key")) or None


def _claim_confidence(claim: L2Phase1FactClaim) -> float:
    return max(0.0, min(1.0, float(claim.confidence or 0.0)))


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "AssessmentActionEligibility",
    "AssessmentCandidateScope",
    "L2ClaimAssessmentValidationMixin",
    "ValidatedClaimAssessment",
]
