"""Endpoint resolution and preference guards for L2 graph validation."""

from __future__ import annotations

from typing import Any, Protocol

from ....event_contracts import MemoryEvent
from ...context_bundle import ResolvedContextRef
from ...models import L2GraphCandidate, ResolvedEntityMention

_PREFERENCE_PREDICATES = {"LIKES", "DISLIKES", "INTERESTED_IN"}


class _L2GraphValidationHostProtocol(Protocol):
    def _non_empty_text(self, value: Any) -> str | None: ...

    def _resolve_self_entity_id(self, event: MemoryEvent) -> str | None: ...

    def _build_concept_node(self, *, entity_type: str, normalized_surface: str) -> str | None: ...

    def _looks_like_interrogative_preference_query(self, text: str | None) -> bool: ...

    def _is_generic_preference_object_id(self, value: str | None) -> bool: ...

    def _is_address_preference_object(self, *, event_text: str | None, value: str | None) -> bool: ...

    def _is_self_like_preference_object(
        self, *, subject_id: str, object_id: str, object_type: str
    ) -> bool: ...


class L2GraphEndpointResolutionMixin:
    """Resolve graph endpoint references and reject unsafe preference edges."""

    def _resolve_phase2_subject_id(self, *, event: MemoryEvent, subject_ref: str) -> str | None:
        host = self._graph_validation_host()
        ref = host._non_empty_text(subject_ref)
        if ref:
            if ref.startswith("user:"):
                return host._resolve_self_entity_id(event) or ref
            return ref
        return host._resolve_self_entity_id(event)

    def _resolve_phase2_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str,
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None = None,
    ) -> str | None:
        host = self._graph_validation_host()
        object_ref = host._non_empty_text(raw_object_ref)
        if not object_ref:
            return None
        if ":" in object_ref:
            return object_ref
        object_ref_casefold = object_ref.casefold()
        for mention in resolved_mentions:
            surfaces = {
                mention.mention_text.strip().casefold(),
                mention.normalized_surface.strip().casefold(),
            }
            resolved_entity_id = host._non_empty_text(mention.resolved_entity_id)
            if object_ref_casefold in surfaces and resolved_entity_id:
                return resolved_entity_id
        if catalog_name_index:
            catalog_hit = catalog_name_index.get(object_ref_casefold)
            if catalog_hit:
                return catalog_hit
        return host._build_concept_node(entity_type=object_type, normalized_surface=object_ref)

    def _should_reject_preference_graph_candidate(
        self,
        *,
        event: MemoryEvent,
        subject_id: str,
        predicate: str,
        object_id: str,
        object_type: str,
        raw_object_ref: str,
    ) -> bool:
        host = self._graph_validation_host()
        if host._is_address_preference_object(
            event_text=event.content,
            value=raw_object_ref,
        ):
            return True
        if predicate not in _PREFERENCE_PREDICATES:
            return False
        if host._looks_like_interrogative_preference_query(event.content):
            return True
        if host._is_generic_preference_object_id(
            object_id
        ) or host._is_generic_preference_object_id(raw_object_ref):
            return True
        if host._is_self_like_preference_object(
            subject_id=subject_id, object_id=object_id, object_type=object_type
        ):
            return True
        return False

    def _resolve_subject_id(
        self, *, event: MemoryEvent, raw_candidate: L2GraphCandidate
    ) -> str | None:
        host = self._graph_validation_host()
        subject_ref = host._non_empty_text(raw_candidate.subject_ref)
        if subject_ref:
            if subject_ref.startswith("user:"):
                return host._resolve_self_entity_id(event) or subject_ref
            return subject_ref
        return host._resolve_self_entity_id(event)

    def _resolve_graph_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str,
        resolved_mentions: list[ResolvedEntityMention],
        resolved_context_refs: list[ResolvedContextRef],
        catalog_name_index: dict[str, str] | None = None,
    ) -> str | None:
        host = self._graph_validation_host()
        object_ref = host._non_empty_text(raw_object_ref)
        if not object_ref:
            return None
        if ":" in object_ref:
            return object_ref
        object_ref_casefold = object_ref.casefold()
        for context_ref in resolved_context_refs:
            if (
                context_ref.surface
                and context_ref.resolved_ref
                and context_ref.surface.casefold() == object_ref_casefold
            ):
                return str(context_ref.resolved_ref)
        for mention in resolved_mentions:
            surfaces = {
                mention.mention_text.strip().casefold(),
                mention.normalized_surface.strip().casefold(),
            }
            resolved_entity_id = host._non_empty_text(mention.resolved_entity_id)
            if object_ref_casefold in surfaces and resolved_entity_id:
                return resolved_entity_id
        if catalog_name_index:
            catalog_hit = catalog_name_index.get(object_ref_casefold)
            if catalog_hit:
                return str(catalog_hit)
        return host._build_concept_node(entity_type=object_type, normalized_surface=object_ref)

    def _graph_validation_host(self) -> _L2GraphValidationHostProtocol:
        return self  # type: ignore[return-value]


__all__ = ["L2GraphEndpointResolutionMixin"]
