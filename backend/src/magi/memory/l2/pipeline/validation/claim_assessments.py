"""Validation of Phase 2 claim-to-record assessments."""

from __future__ import annotations

from typing import Any

from ...models import (
    ContradictionHint,
    L2Phase1FactClaim,
    L2Phase1Result,
    L2Phase2ClaimAssessment,
)

_ALLOWED_RELATIONSHIPS = frozenset({"refines", "contradicts", "evolves"})
_PREFERENCE_PREDICATES = frozenset({"LIKES", "DISLIKES", "INTERESTED_IN"})


class L2ClaimAssessmentValidationMixin:
    """Accept only assessments anchored to known claims and records."""

    def _validate_phase2_claim_assessments(
        self,
        *,
        phase1_result: L2Phase1Result,
        assessments: list[L2Phase2ClaimAssessment],
        existing_graph_edges: list[dict[str, Any]],
        existing_assertions: list[dict[str, Any]],
    ) -> tuple[list[ContradictionHint], int]:
        claims_by_id = {
            claim.claim_id: claim
            for claim in phase1_result.fact_claims
            if str(claim.claim_id or "").strip()
        }
        records_by_id = _existing_records_by_id(existing_graph_edges, existing_assertions)
        hints: list[ContradictionHint] = []
        rejected_count = 0
        for assessment in assessments:
            claim = claims_by_id.get(assessment.claim_id)
            record = records_by_id.get(assessment.related_record_id)
            if (
                claim is None
                or record is None
                or assessment.relationship not in _ALLOWED_RELATIONSHIPS
            ):
                rejected_count += 1
                continue
            if assessment.relationship == "refines":
                continue
            hints.append(
                _contradiction_hint(
                    claim=claim,
                    relationship=assessment.relationship,
                    record=record,
                )
            )
        return hints, rejected_count


def _existing_records_by_id(
    graph_edges: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
) -> dict[str, tuple[str, dict[str, Any]]]:
    records: dict[str, tuple[str, dict[str, Any]]] = {}
    for edge in graph_edges:
        record_id = str(edge.get("triple_id") or "").strip()
        if record_id:
            records[record_id] = ("knowledge_graph", edge)
    for assertion in assertions:
        record_id = str(assertion.get("assertion_id") or "").strip()
        if record_id:
            records[record_id] = ("tom_trait_assertion", assertion)
    return records


def _contradiction_hint(
    *,
    claim: L2Phase1FactClaim,
    relationship: str,
    record: tuple[str, dict[str, Any]],
) -> ContradictionHint:
    record_type, payload = record
    return ContradictionHint(
        target_record_id=_record_id(record_type, payload),
        target_record_type=record_type,
        contradiction_kind=_contradiction_kind(
            claim=claim,
            relationship=relationship,
            record_type=record_type,
            payload=payload,
        ),
        confidence=max(0.0, min(1.0, float(claim.confidence or 0.0))),
        evidence_text=claim.evidence_text,
        recommended_action="revalidate_only",
    )


def _record_id(record_type: str, payload: dict[str, Any]) -> str:
    key = "triple_id" if record_type == "knowledge_graph" else "assertion_id"
    return str(payload.get(key) or "").strip()


def _contradiction_kind(
    *,
    claim: L2Phase1FactClaim,
    relationship: str,
    record_type: str,
    payload: dict[str, Any],
) -> str:
    if relationship == "evolves":
        return "state_reversal"
    existing_predicate = str(payload.get("predicate") or "").strip().upper()
    claim_predicate = str(claim.predicate or "").strip().upper()
    if (
        record_type == "knowledge_graph"
        and claim_predicate in _PREFERENCE_PREDICATES
        and existing_predicate in _PREFERENCE_PREDICATES
    ):
        return "preference_reversal"
    return "direct_negation"


__all__ = ["L2ClaimAssessmentValidationMixin"]
