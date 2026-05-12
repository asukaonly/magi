"""Phase 2 graph edge validation for L2Pipeline."""

from __future__ import annotations

from typing import Any

from ....event_contracts import MemoryEvent
from ...extraction_profiles import ExtractionProfile
from ...models import (
    ContradictionHint,
    L2Phase2ContradictionHint,
    L2Phase2GraphEdge,
    ResolvedEntityMention,
)
from ...ontology import (
    OPEN_PREDICATE_CONFIDENCE_PENALTY,
    PREDICATE_REGISTRY,
    is_reserved_assertion_graph_identifier,
    is_valid_open_predicate,
    validate_graph_candidate,
)
from ...storage.utils import normalize_event_ids


class L2Phase2GraphValidationMixin:
    """Validate Phase 2 graph edges and contradiction hints."""

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
                        "evidence_event_ids": normalize_event_ids(
                            edge.supporting_event_ids or evidence_event_ids
                        ),
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
                {
                    "predicate": predicate,
                    "object_type": object_type,
                    "object_ref": edge.object_ref,
                }
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=edge.subject_ref)  # type: ignore[attr-defined]
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_phase2_object_id(  # type: ignore[attr-defined]
                raw_object_ref=edge.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                rejected_count += 1
                continue
            if is_reserved_assertion_graph_identifier(object_id):
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(  # type: ignore[attr-defined]
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
                    "evidence_event_ids": normalize_event_ids(
                        edge.supporting_event_ids or evidence_event_ids
                    ),
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


__all__ = ["L2Phase2GraphValidationMixin"]
