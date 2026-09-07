"""Deterministic graph projection for grounded Phase 1 claims."""

from __future__ import annotations

from typing import Any, Mapping

from ....event_contracts import MemoryEvent
from ...extraction_profiles import ExtractionProfile
from ...models import L2Phase1Result, ResolvedEntityMention
from ...ontology import (
    PREDICATE_REGISTRY,
    is_low_value_open_predicate,
    is_valid_open_predicate,
    validate_graph_candidate,
)
from ...semantic_routing import SemanticRouteDecision, ProjectionTarget
from .evidence import validate_supporting_event_ids
from ..claim_evidence import ClaimGraphSource
from ..extraction_contracts import ClaimProjectionOutcomeDraft


class L2Phase1GraphProjectionMixin:
    """Project grounded Claims through their persisted route and source authority."""

    def _project_phase1_graph_candidates(
        self,
        *,
        phase1_result: L2Phase1Result,
        semantic_routes: Mapping[str, SemanticRouteDecision],
        event: MemoryEvent,
        evidence_event_ids: list[str],
        resolved_mentions: list[ResolvedEntityMention],
        profile: ExtractionProfile,
        catalog_name_index: dict[str, str] | None = None,
        claim_sources: Mapping[str, ClaimGraphSource],
    ) -> tuple[list[dict[str, Any]], list[ClaimProjectionOutcomeDraft]]:
        candidates: list[dict[str, Any]] = []
        rejected_outcomes: list[ClaimProjectionOutcomeDraft] = []
        for claim in phase1_result.fact_claims:
            candidate, reason_code = self._project_phase1_claim(
                claim=claim,
                route=semantic_routes.get(claim.claim_id),
                event=event,
                evidence_event_ids=evidence_event_ids,
                resolved_mentions=resolved_mentions,
                profile=profile,
                catalog_name_index=catalog_name_index,
                source=claim_sources.get(claim.claim_id),
            )
            if candidate is None:
                outcome = (
                    "skipped"
                    if reason_code in {"assertion_only_route", "negative_claim_requires_scoped_exclusion"}
                    else (
                        "unresolved_entity"
                        if reason_code in {"unresolved_object", "unresolved_subject"}
                        else "rejected"
                    )
                )
                rejected_outcomes.append(
                    ClaimProjectionOutcomeDraft(
                        claim_id=str(getattr(claim, "claim_id", "") or ""),
                        target_kind="relationship",
                        target_id=f"predicate:{str(getattr(claim, 'predicate', '') or '').strip().upper()}",
                        outcome=outcome,
                        reason_code=reason_code or "graph_candidate_rejected",
                    )
                )
                continue
            candidates.append(candidate)
        return candidates, rejected_outcomes

    def _project_phase1_claim(
        self,
        *,
        claim: Any,
        route: SemanticRouteDecision | None,
        event: MemoryEvent,
        evidence_event_ids: list[str],
        resolved_mentions: list[ResolvedEntityMention],
        profile: ExtractionProfile,
        catalog_name_index: dict[str, str] | None,
        source: ClaimGraphSource | None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not profile.allow_graph:
            return None, "graph_projection_disabled"
        claim_id = str(getattr(claim, "claim_id", "") or "").strip()
        if not claim_id:
            return None, "missing_claim_identity"
        supporting_event_ids = validate_supporting_event_ids(
            claim.supporting_event_ids,
            evidence_event_ids,
        )
        if not supporting_event_ids:
            return None, "missing_grounded_support"
        if route is None:
            return None, "missing_semantic_route"
        if source is None:
            return None, "missing_source_authority"
        if not route.can_project_graph:
            if ProjectionTarget.GRAPH in route.projection_targets:
                return None, "unresolved_object"
            if route.can_project_assertion:
                return None, "assertion_only_route"
            return None, route.reason_code
        predicate = self._normalize_predicate(claim.predicate)  # type: ignore[attr-defined]
        fact_kind = self._non_empty_text(claim.fact_kind) or "explicit_fact"  # type: ignore[attr-defined]
        object_type = self._normalize_entity_type(claim.object_type)  # type: ignore[attr-defined]
        if not self._phase1_graph_shape_allowed(
            predicate=predicate,
            object_type=object_type,
            profile=profile,
        ):
            return None, "graph_shape_not_allowed"
        subject_id = route.subject_id
        object_id = route.target_entity_id
        if not subject_id:
            return None, "unresolved_subject"
        if not object_id:
            return None, "unresolved_object"
        return {
            "_claim_id": claim_id,
            "subject_id": subject_id,
            "subject_type": claim.subject_type or "user",
            "predicate": predicate,
            "object_id": object_id,
            "object_type": object_type,
            "fact_kind": fact_kind,
            "evidence_event_ids": supporting_event_ids,
            "confidence": claim.confidence,
            "observed_at": source.event.timestamp,
            "source_type": source.event.source,
            "extraction_method": "llm_phase1_grounded",
            "evidence_text": claim.evidence_text or "",
            "evidence_class": source.evidence_class,
            "valid_from": getattr(claim, "fact_valid_from", None),
            "valid_to": getattr(claim, "fact_valid_to", None),
        }, None

    @staticmethod
    def _phase1_graph_shape_allowed(
        *,
        predicate: str | None,
        object_type: str | None,
        profile: ExtractionProfile,
    ) -> bool:
        if not predicate or not object_type:
            return False
        if object_type not in profile.effective_structured_allowed_entity_types:
            return False
        allowed_predicates = profile.effective_structured_allowed_predicates
        if predicate not in allowed_predicates and not (
            allowed_predicates >= PREDICATE_REGISTRY and is_valid_open_predicate(predicate)
        ):
            return False
        if is_low_value_open_predicate(predicate):
            return False
        is_valid, _ = validate_graph_candidate({"predicate": predicate, "object_type": object_type})
        return is_valid


__all__ = ["L2Phase1GraphProjectionMixin"]
