"""Unified graph candidate preparation helpers for L2Pipeline."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(slots=True)
class _UnifiedGraphCandidateContext:
    event: MemoryEvent
    profile: ExtractionProfile
    resolved_mentions: list[ResolvedEntityMention]
    resolved_context_refs: list[ResolvedContextRef]
    evidence_event_ids: list[str]


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

        context = _UnifiedGraphCandidateContext(
            event=event,
            profile=profile,
            resolved_mentions=resolved_mentions,
            resolved_context_refs=resolved_context_refs,
            evidence_event_ids=evidence_event_ids,
        )
        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for raw_candidate in raw_candidates:
            prepared_candidate = self._prepare_unified_graph_candidate(
                context,
                raw_candidate,
            )
            if prepared_candidate is None:
                rejected_count += 1
                continue
            prepared.append(prepared_candidate)
        return prepared, rejected_count

    def _prepare_unified_graph_candidate(
        self,
        context: _UnifiedGraphCandidateContext,
        raw_candidate: L2GraphCandidate,
    ) -> dict[str, Any] | None:
        object_type = self._normalize_entity_type(raw_candidate.object_type)  # type: ignore[attr-defined]
        predicate = self._normalize_predicate(raw_candidate.predicate)  # type: ignore[attr-defined]
        if not self._profile_allows_graph_candidate(
            context.profile,
            predicate=predicate,
            object_type=object_type,
        ):
            return None

        subject_id = self._resolve_subject_id(  # type: ignore[attr-defined]
            event=context.event,
            raw_candidate=raw_candidate,
        )
        object_id = self._resolve_graph_object_id(  # type: ignore[attr-defined]
            raw_object_ref=raw_candidate.object_ref,
            object_type=object_type,
            resolved_mentions=context.resolved_mentions,
            resolved_context_refs=context.resolved_context_refs,
        )
        if not self._resolved_graph_candidate_is_accepted(
            context=context,
            raw_candidate=raw_candidate,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
        ):
            return None

        return self._prepared_graph_candidate(
            context=context,
            raw_candidate=raw_candidate,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
        )

    def _profile_allows_graph_candidate(
        self,
        profile: ExtractionProfile,
        *,
        predicate: str,
        object_type: str,
    ) -> bool:
        if object_type not in profile.allowed_entity_types:
            return False
        if predicate not in profile.allowed_predicates and not (
            profile.allowed_predicates >= PREDICATE_REGISTRY and is_valid_open_predicate(predicate)
        ):
            return False
        if is_low_value_open_predicate(predicate):
            return False
        is_valid, _ = validate_graph_candidate(
            {
                "predicate": predicate,
                "object_type": object_type,
            }
        )
        return is_valid

    def _resolved_graph_candidate_is_accepted(
        self,
        *,
        context: _UnifiedGraphCandidateContext,
        raw_candidate: L2GraphCandidate,
        subject_id: str | None,
        predicate: str,
        object_id: str | None,
        object_type: str,
    ) -> bool:
        if not subject_id or not object_id:
            return False
        if is_vague_entity_reference(raw_candidate.object_ref):
            return False
        if is_vague_entity_reference(object_id):
            return False
        return not self._should_reject_preference_graph_candidate(  # type: ignore[attr-defined]
            event=context.event,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
            raw_object_ref=raw_candidate.object_ref,
        )

    def _prepared_graph_candidate(
        self,
        *,
        context: _UnifiedGraphCandidateContext,
        raw_candidate: L2GraphCandidate,
        subject_id: str,
        predicate: str,
        object_id: str,
        object_type: str,
    ) -> dict[str, Any]:
        return {
            "subject_id": subject_id,
            "subject_type": raw_candidate.subject_type or "user",
            "predicate": predicate,
            "object_id": object_id,
            "object_type": object_type,
            "evidence_event_ids": normalize_event_ids(
                context.evidence_event_ids or [context.event.event_id]
            ),
            "confidence": (
                raw_candidate.confidence * OPEN_PREDICATE_CONFIDENCE_PENALTY
                if predicate not in PREDICATE_REGISTRY
                else raw_candidate.confidence
            ),
            "observed_at": context.event.timestamp,
            "source_type": context.event.source,
            "extraction_method": "llm_two_phase_extraction",
        }


__all__ = ["L2GraphCandidateValidationMixin"]
