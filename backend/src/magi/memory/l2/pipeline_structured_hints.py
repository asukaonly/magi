"""Structured hint helpers for the L2 cognition pipeline."""

from __future__ import annotations

from typing import Any, Optional, Protocol

from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from .extraction_profiles import ExtractionProfile
from .models import (
    L2Phase1FactClaim,
    L2Phase1Result,
    ResolvedEntityMention,
    StructuredGraphHint,
)
from .ontology import validate_graph_candidate

logger = get_logger(__name__)

_STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS = {
    "public_topology",
    "interaction_evidence",
    "explicit_fact",
}
_STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES = {"source_explicit", "source_structured"}
_STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS = {
    "creator_profile",
    "creator_home",
    "creator_channel",
    "subscription",
    "subscriptions",
}


class _L2StructuredHintHostProtocol(Protocol):
    def _normalize_entity_type(self, raw_value: Any) -> Optional[str]: ...

    def _build_canonical_entity_id(self, *, entity_type: str, canonical_name: str) -> str: ...

    def _non_empty_text(self, value: Any) -> Optional[str]: ...

    def _normalize_predicate(self, raw_value: Any) -> Optional[str]: ...

    def _resolve_phase2_subject_id(self, *, event: MemoryEvent, subject_ref: str) -> str | None: ...

    def _resolve_phase2_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str,
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None = None,
    ) -> str | None: ...

    def _should_reject_preference_graph_candidate(
        self,
        *,
        event: MemoryEvent,
        subject_id: str,
        predicate: str,
        object_id: str,
        object_type: str,
        raw_object_ref: str,
    ) -> bool: ...

    def _normalize_structured_graph_hint_origin_mode(self, raw_value: Any) -> str: ...

    def _extract_structured_graph_hint_facets(
        self,
        attributes: dict[str, Any] | None,
    ) -> list[tuple[str, str]]: ...

    def _normalize_structured_graph_hint_page_kind(
        self,
        attributes: dict[str, Any] | None,
    ) -> str | None: ...


class L2StructuredHintMixin:
    """Own deterministic structured entity and graph hint conversion."""

    def _inject_structured_entity_hints(
        self,
        event: MemoryEvent,
        existing_entities: list[dict[str, Any]],
    ) -> None:
        """Inject structured entity hints into existing_entities as Phase 1 context."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return
        hints = metadata_json.get("structured_entity_hints")
        if not hints or not isinstance(hints, list):
            return

        host = self._structured_hint_host()
        existing_ids = {str(e.get("entity_id", "")) for e in existing_entities}
        injected_count = 0
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            mention_text = str(hint.get("mention_text", "")).strip()
            entity_type = host._normalize_entity_type(hint.get("entity_type"))
            if not mention_text or not entity_type:
                continue

            canonical_name = str(hint.get("canonical_name_hint") or mention_text).strip()
            resolved_id = hint.get("resolved_entity_id")
            if resolved_id:
                entity_id = str(resolved_id)
            else:
                entity_id = host._build_canonical_entity_id(
                    entity_type=entity_type,
                    canonical_name=canonical_name,
                )

            if entity_id in existing_ids:
                continue

            existing_entities.append(
                {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                    "aliases": [canonical_name],
                    "hint_only": True,
                }
            )
            existing_ids.add(entity_id)
            injected_count += 1

        if injected_count:
            logger.debug(
                "L2 structured entity hints injected as context",
                event_id=event.event_id,
                hint_count=len(hints),
                injected_count=injected_count,
            )

    def _inject_structured_graph_hints(
        self,
        event: MemoryEvent,
        phase1_result: L2Phase1Result,
    ) -> None:
        """Inject structured graph hints as deterministic Phase 1 fact claims."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return
        hints = metadata_json.get("structured_graph_hints")
        if not hints or not isinstance(hints, list):
            return

        host = self._structured_hint_host()
        existing_keys = {
            (
                host._non_empty_text(claim.subject_ref) or "",
                host._normalize_predicate(claim.predicate) or "",
                host._non_empty_text(claim.object_ref) or "",
                host._normalize_entity_type(claim.object_type) or "",
            )
            for claim in phase1_result.fact_claims
        }

        injected_count = 0
        for raw_hint in hints:
            if not isinstance(raw_hint, dict):
                continue
            hint = StructuredGraphHint.from_dict(raw_hint)
            subject_ref = host._non_empty_text(hint.subject_ref)
            predicate = host._normalize_predicate(hint.predicate)
            object_ref = host._non_empty_text(hint.object_ref)
            object_type = host._normalize_entity_type(hint.object_type)
            subject_type = host._non_empty_text(hint.subject_type) or "user"
            if not subject_ref or not predicate or not object_ref or not object_type:
                continue

            hint_key = (subject_ref, predicate, object_ref, object_type)
            if hint_key in existing_keys:
                continue

            phase1_result.fact_claims.append(
                L2Phase1FactClaim(
                    subject_ref=subject_ref,
                    subject_type=subject_type,
                    predicate=predicate,
                    object_ref=object_ref,
                    object_type=object_type,
                    fact_kind=host._non_empty_text(hint.fact_kind) or "explicit_fact",
                    polarity="positive",
                    specificity="concrete",
                    evidence_text=host._non_empty_text(hint.evidence_text) or "",
                    confidence=float(hint.confidence if hint.confidence is not None else 1.0),
                    supporting_event_ids=[event.event_id],
                )
            )
            existing_keys.add(hint_key)
            injected_count += 1

        if injected_count:
            logger.debug(
                "L2 structured graph hints injected as fact claims",
                event_id=event.event_id,
                hint_count=len(hints),
                injected_count=injected_count,
            )

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
                    "evidence_event_ids": list(evidence_event_ids or [event.event_id]),
                    "confidence": float(hint.confidence if hint.confidence is not None else 1.0),
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "structured_hint",
                }
            )
        return prepared, rejected_count

    def _build_structured_facet_candidates(
        self,
        *,
        event: MemoryEvent,
        evidence_event_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Convert source-owned structured graph hint attributes into sidecar entity facets."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return []
        raw_hints = metadata_json.get("structured_graph_hints")
        if not isinstance(raw_hints, list) or not raw_hints:
            return []

        host = self._structured_hint_host()
        prepared: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for raw_hint in raw_hints:
            if not isinstance(raw_hint, dict):
                continue
            hint = StructuredGraphHint.from_dict(raw_hint)
            origin_mode = host._normalize_structured_graph_hint_origin_mode(hint.origin_mode)
            if origin_mode not in _STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES:
                continue
            subject_id = host._resolve_phase2_subject_id(event=event, subject_ref=hint.subject_ref)
            subject_type = host._normalize_entity_type(hint.subject_type)
            if not subject_id or not subject_type:
                continue
            for facet_name, facet_value in host._extract_structured_graph_hint_facets(
                hint.attributes
            ):
                key = (subject_id, facet_name, facet_value)
                if key in seen:
                    continue
                seen.add(key)
                prepared.append(
                    {
                        "entity_id": subject_id,
                        "entity_type": subject_type,
                        "facet_name": facet_name,
                        "facet_value": facet_value,
                        "evidence_event_ids": list(evidence_event_ids or [event.event_id]),
                        "confidence": float(
                            hint.confidence if hint.confidence is not None else 1.0
                        ),
                        "observed_at": event.timestamp,
                        "source_type": event.source,
                        "extraction_method": "structured_hint",
                    }
                )
        return prepared

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

    def _structured_hint_host(self) -> _L2StructuredHintHostProtocol:
        return self  # type: ignore[return-value]
