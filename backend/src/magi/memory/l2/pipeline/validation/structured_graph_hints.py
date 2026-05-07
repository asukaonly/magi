"""Structured graph candidate conversion for L2 extraction."""

from __future__ import annotations

from typing import Any

from ....event_contracts import MemoryEvent
from ...extraction_profiles import ExtractionProfile
from ...models import StructuredGraphHint
from ...ontology import validate_graph_candidate
from ...storage.utils import normalize_event_ids
from .structured_hint_common import (
    L2StructuredHintHostMixin,
    _STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS,
    _STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES,
    _STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS,
)


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
    ) -> tuple[list[dict[str, Any]], int]:
        """Convert source-owned structured graph hints into deterministic graph candidates."""
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], 0

        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return [], 0
        raw_hints = metadata_json.get("structured_graph_hints")
        if not isinstance(raw_hints, list) or not raw_hints:
            return [], 0

        host = self._structured_hint_host()
        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for raw_hint in raw_hints:
            if not isinstance(raw_hint, dict):
                continue
            hint = StructuredGraphHint.from_dict(raw_hint)
            object_type = host._normalize_entity_type(hint.object_type)
            predicate = host._normalize_predicate(hint.predicate)
            fact_kind = host._non_empty_text(hint.fact_kind) or "explicit_fact"
            if not object_type or not predicate:
                rejected_count += 1
                continue
            if fact_kind not in _STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS:
                rejected_count += 1
                continue
            if not self._is_structured_graph_hint_directly_admissible(
                hint=hint,
                predicate=predicate,
                fact_kind=fact_kind,
            ):
                rejected_count += 1
                continue
            if object_type not in profile.effective_structured_allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.effective_structured_allowed_predicates:
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate(
                {"predicate": predicate, "object_type": object_type}
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = host._resolve_phase2_subject_id(event=event, subject_ref=hint.subject_ref)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = host._resolve_phase2_object_id(
                raw_object_ref=hint.object_ref,
                object_type=object_type,
                resolved_mentions=[],
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                rejected_count += 1
                continue
            if host._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=hint.object_ref,
            ):
                rejected_count += 1
                continue

            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": host._non_empty_text(hint.subject_type) or "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "fact_kind": fact_kind,
                    "evidence_event_ids": normalize_event_ids(
                        evidence_event_ids or [event.event_id]
                    ),
                    "confidence": float(hint.confidence if hint.confidence is not None else 1.0),
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "structured_hint",
                }
            )
        return prepared, rejected_count

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
