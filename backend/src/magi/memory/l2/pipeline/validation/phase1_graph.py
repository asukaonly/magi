"""Deterministic graph projection for grounded Phase 1 claims."""

from __future__ import annotations

from typing import Any

from ....event_contracts import MemoryEvent
from ....evidence import EvidenceClassification
from ...extraction_profiles import ExtractionProfile
from ...models import L2Phase1Result, ResolvedEntityMention
from ...ontology import (
    PREDICATE_REGISTRY,
    is_low_value_open_predicate,
    is_valid_open_predicate,
    validate_graph_candidate,
)
from .evidence import validate_supporting_event_ids


class L2Phase1GraphProjectionMixin:
    """Project grounded Phase 1 facts without asking Phase 2 to restate them."""

    def _project_phase1_graph_candidates(
        self,
        *,
        phase1_result: L2Phase1Result,
        event: MemoryEvent,
        evidence_event_ids: list[str],
        resolved_mentions: list[ResolvedEntityMention],
        profile: ExtractionProfile,
        catalog_name_index: dict[str, str] | None = None,
        classification: EvidenceClassification | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        candidates: list[dict[str, Any]] = []
        rejected_count = 0
        for claim in phase1_result.fact_claims:
            candidate = self._project_phase1_claim(
                claim=claim,
                event=event,
                evidence_event_ids=evidence_event_ids,
                resolved_mentions=resolved_mentions,
                profile=profile,
                catalog_name_index=catalog_name_index,
                classification=classification,
            )
            if candidate is None:
                rejected_count += 1
                continue
            candidates.append(candidate)
        return candidates, rejected_count

    def _project_phase1_claim(
        self,
        *,
        claim: Any,
        event: MemoryEvent,
        evidence_event_ids: list[str],
        resolved_mentions: list[ResolvedEntityMention],
        profile: ExtractionProfile,
        catalog_name_index: dict[str, str] | None,
        classification: EvidenceClassification | None,
    ) -> dict[str, Any] | None:
        if not profile.allow_graph or not str(getattr(claim, "claim_id", "") or "").strip():
            return None
        supporting_event_ids = validate_supporting_event_ids(
            claim.supporting_event_ids,
            evidence_event_ids,
        )
        if not supporting_event_ids:
            return None
        predicate = self._normalize_predicate(claim.predicate)  # type: ignore[attr-defined]
        object_type = self._normalize_entity_type(claim.object_type)  # type: ignore[attr-defined]
        if not self._phase1_graph_shape_allowed(
            predicate=predicate,
            object_type=object_type,
            profile=profile,
        ):
            return None
        subject_id = self._resolve_phase2_subject_id(  # type: ignore[attr-defined]
            event=event,
            subject_ref=claim.subject_ref,
        )
        object_id = self._resolve_phase2_object_id(  # type: ignore[attr-defined]
            raw_object_ref=claim.object_ref,
            object_type=object_type,
            resolved_mentions=resolved_mentions,
            catalog_name_index=catalog_name_index,
        )
        if not subject_id or not object_id:
            return None
        if self._should_reject_preference_graph_candidate(  # type: ignore[attr-defined]
            event=event,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
            raw_object_ref=claim.object_ref,
        ):
            return None
        return {
            "subject_id": subject_id,
            "subject_type": claim.subject_type or "user",
            "predicate": predicate,
            "object_id": object_id,
            "object_type": object_type,
            "fact_kind": self._non_empty_text(claim.fact_kind) or "explicit_fact",  # type: ignore[attr-defined]
            "evidence_event_ids": supporting_event_ids,
            "confidence": claim.confidence,
            "observed_at": event.timestamp,
            "source_type": event.source,
            "extraction_method": "llm_phase1_grounded",
            "evidence_text": claim.evidence_text or "",
            "evidence_class": (
                classification.evidence_class if classification is not None else None
            ),
        }

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
        is_valid, _ = validate_graph_candidate(
            {"predicate": predicate, "object_type": object_type}
        )
        return is_valid

    @staticmethod
    def _phase2_inference_required(
        *,
        phase1_result: L2Phase1Result,
        profile: ExtractionProfile,
        policy: Any,
    ) -> bool:
        assertion_mode = str(
            getattr(profile, "assertion_mode", "phase2_candidate") or ""
        ).strip().casefold()
        return bool(
            phase1_result.fact_claims
            and policy.allow_assertion_write
            and profile.allow_assertion
            and assertion_mode == "phase2_candidate"
        )


__all__ = ["L2Phase1GraphProjectionMixin"]
