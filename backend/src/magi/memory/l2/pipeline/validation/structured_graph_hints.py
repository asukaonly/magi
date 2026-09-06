"""Structured graph candidate conversion for L2 extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....event_contracts import MemoryEvent
from ....evidence import EvidenceClassification
from ...extraction_profiles import ExtractionProfile
from ...entities.identity import entity_hint_id, normalized_entity_name
from ...models import StructuredGraphHint
from ...ontology import validate_graph_candidate
from ...storage.utils import normalize_event_ids
from .structured_hint_common import (
    L2StructuredHintHostMixin,
    _STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS,
    _STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES,
    _STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS,
)


@dataclass(frozen=True, slots=True)
class _StructuredGraphHintShape:
    hint: StructuredGraphHint
    object_type: str
    predicate: str
    fact_kind: str


@dataclass(frozen=True, slots=True)
class _StructuredGraphHintEndpoints:
    subject_id: str
    object_id: str


class L2StructuredGraphHintMixin(L2StructuredHintHostMixin):
    """Convert source-owned structured graph hints into deterministic candidates."""

    def _build_structured_graph_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        evidence_event_ids: list[str],
        catalog_name_index: dict[str, str] | None = None,
        classification: EvidenceClassification | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Convert source-owned structured graph hints into deterministic graph candidates."""
        if not self._allows_structured_graph_candidates(profile=profile, policy=policy):
            return [], 0

        raw_hints = self._structured_graph_hint_payloads(event)
        if not raw_hints:
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for raw_hint in raw_hints:
            if not isinstance(raw_hint, dict):
                continue
            candidate = self._build_structured_graph_candidate(
                raw_hint=raw_hint,
                event=event,
                profile=profile,
                evidence_event_ids=evidence_event_ids,
                catalog_name_index=catalog_name_index,
                classification=classification,
            )
            if candidate is None:
                rejected_count += 1
                continue
            prepared.append(candidate)
        return prepared, rejected_count

    @staticmethod
    def _allows_structured_graph_candidates(*, profile: ExtractionProfile, policy: Any) -> bool:
        return bool(
            policy.allow_graph_write and profile.allow_graph and policy.graph_scope == "full"
        )

    @staticmethod
    def _structured_graph_hint_payloads(event: MemoryEvent) -> list[Any]:
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return []
        raw_hints = metadata_json.get("structured_graph_hints")
        if not isinstance(raw_hints, list):
            return []
        return raw_hints

    def _build_structured_graph_candidate(
        self,
        *,
        raw_hint: dict[str, Any],
        event: MemoryEvent,
        profile: ExtractionProfile,
        evidence_event_ids: list[str],
        catalog_name_index: dict[str, str] | None,
        classification: EvidenceClassification | None,
    ) -> dict[str, Any] | None:
        hint = StructuredGraphHint.from_dict(raw_hint)
        shape = self._structured_graph_hint_shape(hint=hint, profile=profile)
        if shape is None:
            return None
        endpoints = self._structured_graph_hint_endpoints(
            event=event,
            shape=shape,
            catalog_name_index=catalog_name_index,
        )
        if endpoints is None:
            return None
        if self._should_reject_structured_graph_hint(
            event=event,
            shape=shape,
            endpoints=endpoints,
        ):
            return None
        return self._structured_graph_candidate_payload(
            event=event,
            shape=shape,
            endpoints=endpoints,
            evidence_event_ids=evidence_event_ids,
            classification=classification,
        )

    def _structured_graph_hint_shape(
        self,
        *,
        hint: StructuredGraphHint,
        profile: ExtractionProfile,
    ) -> _StructuredGraphHintShape | None:
        host = self._structured_hint_host()
        object_type = host._normalize_entity_type(hint.object_type)
        predicate = host._normalize_predicate(hint.predicate)
        fact_kind = host._non_empty_text(hint.fact_kind) or "explicit_fact"
        if not object_type or not predicate:
            return None
        if fact_kind not in _STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS:
            return None
        if not self._is_structured_graph_hint_directly_admissible(
            hint=hint,
            predicate=predicate,
            fact_kind=fact_kind,
        ):
            return None
        if object_type not in profile.effective_structured_allowed_entity_types:
            return None
        if predicate not in profile.effective_structured_allowed_predicates:
            return None
        is_valid, _ = validate_graph_candidate({"predicate": predicate, "object_type": object_type})
        if not is_valid:
            return None
        return _StructuredGraphHintShape(
            hint=hint,
            object_type=object_type,
            predicate=predicate,
            fact_kind=fact_kind,
        )

    def _structured_graph_hint_endpoints(
        self,
        *,
        event: MemoryEvent,
        shape: _StructuredGraphHintShape,
        catalog_name_index: dict[str, str] | None,
    ) -> _StructuredGraphHintEndpoints | None:
        host = self._structured_hint_host()
        subject_id = host._resolve_phase2_subject_id(
            event=event,
            subject_ref=shape.hint.subject_ref,
        )
        if not subject_id:
            return None
        for hint in (event.metadata_json or {}).get("structured_entity_hints", []):
            if not isinstance(hint, dict) or not hint.get("source_entity_key"):
                continue
            if hint.get("entity_type") == shape.object_type and normalized_entity_name(shape.hint.object_ref) in {normalized_entity_name(str(hint.get("mention_text") or "")), normalized_entity_name(str(hint.get("canonical_name_hint") or ""))}:
                return _StructuredGraphHintEndpoints(subject_id, entity_hint_id(hint, source=event.source, event_id=event.event_id))
        object_id = host._resolve_phase2_object_id(
            raw_object_ref=shape.hint.object_ref,
            object_type=shape.object_type,
            resolved_mentions=[],
            catalog_name_index=catalog_name_index,
        )
        if not object_id:
            return None
        return _StructuredGraphHintEndpoints(subject_id=subject_id, object_id=object_id)

    def _should_reject_structured_graph_hint(
        self,
        *,
        event: MemoryEvent,
        shape: _StructuredGraphHintShape,
        endpoints: _StructuredGraphHintEndpoints,
    ) -> bool:
        return self._structured_hint_host()._should_reject_preference_graph_candidate(
            event=event,
            subject_id=endpoints.subject_id,
            predicate=shape.predicate,
            object_id=endpoints.object_id,
            object_type=shape.object_type,
            raw_object_ref=shape.hint.object_ref,
        )

    def _structured_graph_candidate_payload(
        self,
        *,
        event: MemoryEvent,
        shape: _StructuredGraphHintShape,
        endpoints: _StructuredGraphHintEndpoints,
        evidence_event_ids: list[str],
        classification: EvidenceClassification | None,
    ) -> dict[str, Any]:
        host = self._structured_hint_host()
        return {
            "subject_id": endpoints.subject_id,
            "subject_type": host._non_empty_text(shape.hint.subject_type) or "user",
            "predicate": shape.predicate,
            "object_id": endpoints.object_id,
            "object_type": shape.object_type,
            "fact_kind": shape.fact_kind,
            "evidence_event_ids": normalize_event_ids(evidence_event_ids or [event.event_id]),
            "confidence": float(
                shape.hint.confidence if shape.hint.confidence is not None else 1.0
            ),
            "observed_at": event.timestamp,
            "source_type": event.source,
            "extraction_method": "structured_hint",
            "evidence_class": (
                classification.evidence_class if classification is not None else None
            ),
        }

    def _is_structured_graph_hint_directly_admissible(
        self,
        *,
        hint: StructuredGraphHint,
        predicate: str | None,
        fact_kind: str,
    ) -> bool:
        """Return whether a source-owned graph hint may bypass LLM edge generation."""
        host = self._structured_hint_host()
        canonical_predicate = host._normalize_predicate(predicate)
        if canonical_predicate is None:
            return False

        origin_mode = host._normalize_structured_graph_hint_origin_mode(hint.origin_mode)
        if origin_mode not in _STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES:
            return False

        if fact_kind in {"public_topology", "explicit_fact"}:
            return True

        if fact_kind != "interaction_evidence":
            return False

        if canonical_predicate != "FOLLOWS":
            return True

        page_kind = host._normalize_structured_graph_hint_page_kind(hint.attributes)
        return page_kind in _STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS


__all__ = ["L2StructuredGraphHintMixin"]
