"""Graph candidate validation and resolution helpers for L2Pipeline."""

from __future__ import annotations

from typing import Any

from ....event_contracts import MemoryEvent
from ...context_bundle import ResolvedContextRef
from ...extraction_profiles import ExtractionProfile
from ...models import (
    ContradictionHint,
    L2GraphCandidate,
    L2Phase1Result,
    L2Phase2ContradictionHint,
    L2Phase2GraphEdge,
    ResolvedEntityMention,
)
from ...ontology import (
    OPEN_PREDICATE_CONFIDENCE_PENALTY,
    PREDICATE_REGISTRY,
    is_valid_open_predicate,
    validate_graph_candidate,
)
from .graph_resolution import L2GraphEndpointResolutionMixin

class L2GraphValidationMixin(L2GraphEndpointResolutionMixin):
    """Validate graph candidates and resolve graph endpoint references."""

    def _validate_phase2_graph_edges(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        resolved_mentions: list[ResolvedEntityMention],
        evidence_event_ids: list[str],
        phase2_edges: list[L2Phase2GraphEdge],
        catalog_name_index: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """Validate Phase 2 graph edges against ontology and profile constraints."""
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], [], 0

        prepared: list[dict[str, Any]] = []
        corroborate_targets: list[dict[str, Any]] = []
        rejected_count = 0
        for edge in phase2_edges:
            if edge.relationship_to_existing == "corroborates" and edge.related_existing_triple_id:
                corroborate_targets.append(
                    {
                        "triple_id": edge.related_existing_triple_id,
                        "evidence_event_ids": list(edge.supporting_event_ids or evidence_event_ids),
                        "new_confidence": edge.confidence,
                        "observed_at": event.timestamp,
                        "evidence_text": edge.evidence_text or "",
                    }
                )
                continue

            object_type = self._normalize_entity_type(edge.object_type)  # type: ignore[attr-defined]
            predicate = self._normalize_predicate(edge.predicate)  # type: ignore[attr-defined]
            if object_type not in profile.effective_structured_allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.effective_structured_allowed_predicates and not (
                profile.effective_structured_allowed_predicates >= PREDICATE_REGISTRY
                and is_valid_open_predicate(predicate)
            ):
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate(
                {"predicate": predicate, "object_type": object_type}
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=edge.subject_ref)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_phase2_object_id(
                raw_object_ref=edge.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=edge.object_ref,
            ):
                rejected_count += 1
                continue
            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": edge.subject_type or "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "fact_kind": self._non_empty_text(edge.fact_kind) or "explicit_fact",  # type: ignore[attr-defined]
                    "evidence_event_ids": list(edge.supporting_event_ids or evidence_event_ids),
                    "confidence": (
                        edge.confidence * OPEN_PREDICATE_CONFIDENCE_PENALTY
                        if predicate not in PREDICATE_REGISTRY
                        else edge.confidence
                    ),
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "llm_phase2_integration",
                    "evidence_text": edge.evidence_text or "",
                }
            )
        return prepared, corroborate_targets, rejected_count

    def _can_fast_track(
        self,
        *,
        phase1_result: L2Phase1Result,
        resolved_mentions: list[ResolvedEntityMention],
        existing_graph_edges: list[dict[str, Any]],
        profile: ExtractionProfile,
        policy: Any,
    ) -> bool:
        """Return True when Phase 1 output is simple enough to skip Phase 2."""
        if not phase1_result.fact_claims:
            return False
        if policy.allow_assertion_write:
            return False
        for claim in phase1_result.fact_claims:
            if self._normalize_predicate(claim.predicate) not in PREDICATE_REGISTRY:  # type: ignore[attr-defined]
                return False
        for entity in phase1_result.entities:
            if getattr(entity, "is_new", False):
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
            object_id = self._resolve_phase2_object_id(
                raw_object_ref=claim.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=None,
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
    ) -> list[dict[str, Any]]:
        """Convert Phase 1 fact claims directly to graph candidates (no Phase 2)."""
        candidates: list[dict[str, Any]] = []
        for claim in phase1_result.fact_claims:
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
            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=claim.subject_ref)
            if not subject_id:
                continue
            object_id = self._resolve_phase2_object_id(
                raw_object_ref=claim.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                continue
            if self._should_reject_preference_graph_candidate(
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
                    "evidence_event_ids": list(claim.supporting_event_ids or evidence_event_ids),
                    "confidence": claim.confidence,
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "llm_phase1_fast_track",
                    "evidence_text": claim.evidence_text or "",
                }
            )
        return candidates

    def _merge_graph_candidates(
        self, *candidate_groups: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Merge graph candidates by triple identity, preferring structured hints."""
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for group in candidate_groups:
            for candidate in group:
                key = (
                    str(candidate.get("subject_id") or ""),
                    str(candidate.get("predicate") or ""),
                    str(candidate.get("object_id") or ""),
                )
                if not all(key):
                    continue
                existing = merged.get(key)
                if existing is None:
                    merged[key] = dict(candidate)
                    continue

                existing_method = str(existing.get("extraction_method") or "")
                candidate_method = str(candidate.get("extraction_method") or "")
                preferred = (
                    dict(candidate)
                    if candidate_method == "structured_hint"
                    and existing_method != "structured_hint"
                    else dict(existing)
                )
                preferred["evidence_event_ids"] = sorted(
                    set(existing.get("evidence_event_ids") or []).union(
                        candidate.get("evidence_event_ids") or []
                    )
                )
                preferred["confidence"] = max(
                    float(existing.get("confidence") or 0.0),
                    float(candidate.get("confidence") or 0.0),
                )
                preferred["fact_kind"] = (
                    str(candidate.get("fact_kind") or "").strip()
                    if candidate_method == "structured_hint"
                    and str(candidate.get("fact_kind") or "").strip()
                    else str(
                        preferred.get("fact_kind")
                        or existing.get("fact_kind")
                        or candidate.get("fact_kind")
                        or "explicit_fact"
                    )
                )
                merged[key] = preferred
        return list(merged.values())

    def _convert_phase2_contradiction_hints(
        self,
        phase2_hints: list[L2Phase2ContradictionHint],
    ) -> list[ContradictionHint]:
        """Convert Phase 2 contradiction hints to the ContradictionHint format."""
        hints: list[ContradictionHint] = []
        for h in phase2_hints:
            if not h.target_record_id or not h.target_record_type or not h.contradiction_kind:
                continue
            hints.append(
                ContradictionHint(
                    target_record_id=h.target_record_id,
                    target_record_type=h.target_record_type,
                    contradiction_kind=h.contradiction_kind,
                    confidence=h.confidence,
                    evidence_text=h.evidence_text,
                    recommended_action=h.recommended_action,
                )
            )
        return hints

    def _prepare_unified_graph_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        resolved_mentions: list[ResolvedEntityMention],
        resolved_context_refs: list[ResolvedContextRef],
        evidence_event_ids: list[str],
        raw_candidates: list[L2GraphCandidate],
    ) -> tuple[list[dict[str, Any]], int]:
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for raw_candidate in raw_candidates:
            object_type = self._normalize_entity_type(raw_candidate.object_type)  # type: ignore[attr-defined]
            predicate = self._normalize_predicate(raw_candidate.predicate)  # type: ignore[attr-defined]
            if object_type not in profile.allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.allowed_predicates and not (
                profile.allowed_predicates >= PREDICATE_REGISTRY
                and is_valid_open_predicate(predicate)
            ):
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate(
                {
                    "predicate": predicate,
                    "object_type": object_type,
                }
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_subject_id(event=event, raw_candidate=raw_candidate)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_graph_object_id(
                raw_object_ref=raw_candidate.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                resolved_context_refs=resolved_context_refs,
            )
            if not object_id:
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=raw_candidate.object_ref,
            ):
                rejected_count += 1
                continue
            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": raw_candidate.subject_type or "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "evidence_event_ids": list(evidence_event_ids or [event.event_id]),
                    "confidence": (
                        raw_candidate.confidence * OPEN_PREDICATE_CONFIDENCE_PENALTY
                        if predicate not in PREDICATE_REGISTRY
                        else raw_candidate.confidence
                    ),
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "llm_two_phase_extraction",
                }
            )
        return prepared, rejected_count

__all__ = ["L2GraphValidationMixin"]
