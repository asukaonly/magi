"""Phase 1 graph fast-track helpers for L2Pipeline."""

from __future__ import annotations

from typing import Any

from ....event_contracts import MemoryEvent
from ....evidence import EvidenceClassification
from ...extraction_profiles import ExtractionProfile
from ...models import L2Phase1Result, ResolvedEntityMention
from ...ontology import PREDICATE_REGISTRY, validate_graph_candidate
from .evidence import validate_supporting_event_ids


class L2GraphFastTrackMixin:
    """Decide and materialize Phase 1 graph fast-track candidates."""

    def _can_fast_track(
        self,
        *,
        phase1_result: L2Phase1Result,
        resolved_mentions: list[ResolvedEntityMention],
        existing_graph_edges: list[dict[str, Any]],
        profile: ExtractionProfile,
        policy: Any,
        catalog_name_index: dict[str, str] | None = None,
    ) -> bool:
        """Return True when Phase 1 output is simple enough to skip Phase 2."""
        if not phase1_result.fact_claims:
            return False
        if policy.allow_assertion_write and profile.allow_assertion:
            return False
        for claim in phase1_result.fact_claims:
            if self._normalize_predicate(claim.predicate) not in PREDICATE_REGISTRY:  # type: ignore[attr-defined]
                return False
        if any(
            claim.fact_kind and "assertion" in claim.fact_kind.lower()
            for claim in phase1_result.fact_claims
        ):
            return False
        existing_predicates_by_pair: dict[tuple[str, str], set[str]] = {}
        for edge in existing_graph_edges:
            pair = (str(edge.get("subject_id", "")), str(edge.get("object_id", "")))
            existing_predicates_by_pair.setdefault(pair, set()).add(str(edge.get("predicate", "")))
        for claim in phase1_result.fact_claims:
            predicate = self._normalize_predicate(claim.predicate)  # type: ignore[attr-defined]
            object_type = self._normalize_entity_type(claim.object_type)  # type: ignore[attr-defined]
            object_id = self._resolve_phase2_object_id(  # type: ignore[attr-defined]
                raw_object_ref=claim.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                return False
            if object_type not in profile.effective_structured_allowed_entity_types:
                return False
            if predicate not in profile.effective_structured_allowed_predicates:
                return False
        return True

    def _fast_track_claims_to_candidates(
        self,
        *,
        phase1_result: L2Phase1Result,
        event: MemoryEvent,
        evidence_event_ids: list[str],
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None = None,
        profile: ExtractionProfile,
        classification: EvidenceClassification | None = None,
    ) -> list[dict[str, Any]]:
        """Convert Phase 1 fact claims directly to graph candidates (no Phase 2)."""
        candidates: list[dict[str, Any]] = []
        for claim in phase1_result.fact_claims:
            supporting_event_ids = validate_supporting_event_ids(
                claim.supporting_event_ids,
                evidence_event_ids,
            )
            if not supporting_event_ids:
                continue
            predicate = self._normalize_predicate(claim.predicate)  # type: ignore[attr-defined]
            object_type = self._normalize_entity_type(claim.object_type)  # type: ignore[attr-defined]
            if object_type not in profile.effective_structured_allowed_entity_types:
                continue
            if predicate not in profile.effective_structured_allowed_predicates:
                continue
            is_valid, _ = validate_graph_candidate(
                {"predicate": predicate, "object_type": object_type}
            )
            if not is_valid:
                continue
            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=claim.subject_ref)  # type: ignore[attr-defined]
            if not subject_id:
                continue
            object_id = self._resolve_phase2_object_id(  # type: ignore[attr-defined]
                raw_object_ref=claim.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                continue
            if self._should_reject_preference_graph_candidate(  # type: ignore[attr-defined]
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=claim.object_ref,
            ):
                continue
            candidates.append(
                {
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
                    "extraction_method": "llm_phase1_fast_track",
                    "evidence_text": claim.evidence_text or "",
                    "evidence_class": (
                        classification.evidence_class if classification is not None else None
                    ),
                }
            )
        return candidates


__all__ = ["L2GraphFastTrackMixin"]
