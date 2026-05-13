"""Unified graph candidate preparation helpers for L2Pipeline."""

from __future__ import annotations

from typing import Any

from ....event_contracts import MemoryEvent
from ...context_bundle import ResolvedContextRef
from ...extraction_profiles import ExtractionProfile
from ...models import L2GraphCandidate, ResolvedEntityMention
from ...ontology import (
    OPEN_PREDICATE_CONFIDENCE_PENALTY,
    PREDICATE_REGISTRY,
    is_low_value_open_predicate,
    is_vague_entity_reference,
    is_valid_open_predicate,
    validate_graph_candidate,
)
from ...storage.utils import normalize_event_ids


class L2GraphCandidateValidationMixin:
    """Merge and prepare graph candidates from legacy/unified extraction paths."""

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
                    set(normalize_event_ids(existing.get("evidence_event_ids") or [])).union(
                        normalize_event_ids(candidate.get("evidence_event_ids") or [])
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
            if is_low_value_open_predicate(predicate):
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

            subject_id = self._resolve_subject_id(event=event, raw_candidate=raw_candidate)  # type: ignore[attr-defined]
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_graph_object_id(  # type: ignore[attr-defined]
                raw_object_ref=raw_candidate.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                resolved_context_refs=resolved_context_refs,
            )
            if not object_id:
                rejected_count += 1
                continue
            if is_vague_entity_reference(raw_candidate.object_ref) or is_vague_entity_reference(object_id):
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(  # type: ignore[attr-defined]
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
                    "evidence_event_ids": normalize_event_ids(
                        evidence_event_ids or [event.event_id]
                    ),
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


__all__ = ["L2GraphCandidateValidationMixin"]
