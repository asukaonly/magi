"""Phase 2 graph edge validation for L2Pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....event_contracts import MemoryEvent
from ....evidence import EvidenceClassification
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
    is_low_value_open_predicate,
    is_reserved_assertion_graph_identifier,
    is_vague_entity_reference,
    is_valid_open_predicate,
    validate_graph_candidate,
)
from .evidence import validate_supporting_event_ids


@dataclass(frozen=True)
class _Phase2GraphEdgeShape:
    object_type: str
    predicate: str


@dataclass(frozen=True)
class _Phase2GraphEndpoints:
    subject_id: str
    object_id: str


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
        profile_signal_object_refs: set[str] | None = None,
        catalog_name_index: dict[str, str] | None = None,
        classification: EvidenceClassification | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """Validate Phase 2 graph edges against ontology and profile constraints."""
        if not self._phase2_graph_write_enabled(profile=profile, policy=policy):
            return [], [], 0

        prepared: list[dict[str, Any]] = []
        corroborate_targets: list[dict[str, Any]] = []
        rejected_count = 0
        for edge in phase2_edges:
            supporting_event_ids = validate_supporting_event_ids(
                edge.supporting_event_ids,
                evidence_event_ids,
            )
            if not supporting_event_ids:
                rejected_count += 1
                continue
            corroborate_target = self._build_phase2_corroborate_target(
                event=event,
                edge=edge,
                supporting_event_ids=supporting_event_ids,
            )
            if corroborate_target is not None:
                corroborate_targets.append(corroborate_target)
                continue

            candidate = self._prepare_phase2_graph_edge(
                event=event,
                profile=profile,
                resolved_mentions=resolved_mentions,
                supporting_event_ids=supporting_event_ids,
                edge=edge,
                profile_signal_object_refs=profile_signal_object_refs,
                catalog_name_index=catalog_name_index,
                classification=classification,
            )
            if candidate is None:
                rejected_count += 1
                continue
            prepared.append(candidate)
        return prepared, corroborate_targets, rejected_count

    @staticmethod
    def _phase2_graph_write_enabled(*, profile: ExtractionProfile, policy: Any) -> bool:
        return bool(
            policy.allow_graph_write and profile.allow_graph and policy.graph_scope == "full"
        )

    @staticmethod
    def _build_phase2_corroborate_target(
        *,
        event: MemoryEvent,
        edge: L2Phase2GraphEdge,
        supporting_event_ids: list[str],
    ) -> dict[str, Any] | None:
        if edge.relationship_to_existing != "corroborates" or not edge.related_existing_triple_id:
            return None
        return {
            "triple_id": edge.related_existing_triple_id,
            "evidence_event_ids": supporting_event_ids,
            "new_confidence": edge.confidence,
            "observed_at": event.timestamp,
            "evidence_text": edge.evidence_text or "",
        }

    def _prepare_phase2_graph_edge(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        resolved_mentions: list[ResolvedEntityMention],
        supporting_event_ids: list[str],
        edge: L2Phase2GraphEdge,
        profile_signal_object_refs: set[str] | None,
        catalog_name_index: dict[str, str] | None,
        classification: EvidenceClassification | None,
    ) -> dict[str, Any] | None:
        shape = self._normalize_phase2_graph_edge_shape(edge)
        if not self._phase2_graph_shape_allowed(edge=edge, shape=shape, profile=profile):
            return None
        endpoints = self._resolve_phase2_graph_endpoints(
            event=event,
            edge=edge,
            shape=shape,
            resolved_mentions=resolved_mentions,
            catalog_name_index=catalog_name_index,
        )
        if endpoints is None:
            return None
        if self._phase2_graph_object_rejected(
            edge=edge,
            object_id=endpoints.object_id,
            profile_signal_object_refs=profile_signal_object_refs,
        ):
            return None
        if self._should_reject_preference_graph_candidate(  # type: ignore[attr-defined]
            event=event,
            subject_id=endpoints.subject_id,
            predicate=shape.predicate,
            object_id=endpoints.object_id,
            object_type=shape.object_type,
            raw_object_ref=edge.object_ref,
        ):
            return None
        return self._build_phase2_graph_candidate(
            event=event,
            edge=edge,
            shape=shape,
            endpoints=endpoints,
            supporting_event_ids=supporting_event_ids,
            classification=classification,
        )

    def _normalize_phase2_graph_edge_shape(
        self,
        edge: L2Phase2GraphEdge,
    ) -> _Phase2GraphEdgeShape:
        return _Phase2GraphEdgeShape(
            object_type=self._normalize_entity_type(edge.object_type),  # type: ignore[attr-defined]
            predicate=self._normalize_predicate(edge.predicate),  # type: ignore[attr-defined]
        )

    @staticmethod
    def _phase2_graph_shape_allowed(
        *,
        edge: L2Phase2GraphEdge,
        shape: _Phase2GraphEdgeShape,
        profile: ExtractionProfile,
    ) -> bool:
        if shape.object_type not in profile.effective_structured_allowed_entity_types:
            return False
        if shape.predicate not in profile.effective_structured_allowed_predicates and not (
            profile.effective_structured_allowed_predicates >= PREDICATE_REGISTRY
            and is_valid_open_predicate(shape.predicate)
        ):
            return False
        if is_low_value_open_predicate(shape.predicate):
            return False
        is_valid, _ = validate_graph_candidate(
            {
                "predicate": shape.predicate,
                "object_type": shape.object_type,
                "object_ref": edge.object_ref,
            }
        )
        return is_valid

    def _resolve_phase2_graph_endpoints(
        self,
        *,
        event: MemoryEvent,
        edge: L2Phase2GraphEdge,
        shape: _Phase2GraphEdgeShape,
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None,
    ) -> _Phase2GraphEndpoints | None:
        subject_id = self._resolve_phase2_subject_id(  # type: ignore[attr-defined]
            event=event,
            subject_ref=edge.subject_ref,
        )
        if not subject_id:
            return None
        object_id = self._resolve_phase2_object_id(  # type: ignore[attr-defined]
            raw_object_ref=edge.object_ref,
            object_type=shape.object_type,
            resolved_mentions=resolved_mentions,
            catalog_name_index=catalog_name_index,
        )
        if not object_id:
            return None
        return _Phase2GraphEndpoints(subject_id=subject_id, object_id=object_id)

    def _phase2_graph_object_rejected(
        self,
        *,
        edge: L2Phase2GraphEdge,
        object_id: str,
        profile_signal_object_refs: set[str] | None,
    ) -> bool:
        if is_reserved_assertion_graph_identifier(object_id):
            return True
        if is_vague_entity_reference(edge.object_ref) or is_vague_entity_reference(object_id):
            return True
        normalized_object_ref = self._normalize_profile_signal_value(edge.object_ref)  # type: ignore[attr-defined]
        return bool(
            normalized_object_ref and normalized_object_ref in (profile_signal_object_refs or set())
        )

    def _build_phase2_graph_candidate(
        self,
        *,
        event: MemoryEvent,
        edge: L2Phase2GraphEdge,
        shape: _Phase2GraphEdgeShape,
        endpoints: _Phase2GraphEndpoints,
        supporting_event_ids: list[str],
        classification: EvidenceClassification | None,
    ) -> dict[str, Any]:
        return {
            "subject_id": endpoints.subject_id,
            "subject_type": edge.subject_type or "user",
            "predicate": shape.predicate,
            "object_id": endpoints.object_id,
            "object_type": shape.object_type,
            "fact_kind": self._non_empty_text(edge.fact_kind) or "explicit_fact",  # type: ignore[attr-defined]
            "evidence_event_ids": supporting_event_ids,
            "confidence": (
                edge.confidence * OPEN_PREDICATE_CONFIDENCE_PENALTY
                if shape.predicate not in PREDICATE_REGISTRY
                else edge.confidence
            ),
            "observed_at": event.timestamp,
            "source_type": event.source,
            "extraction_method": "llm_phase2_integration",
            "evidence_text": edge.evidence_text or "",
            "evidence_class": (
                classification.evidence_class if classification is not None else None
            ),
        }

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
