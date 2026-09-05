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
        return self._resolve_object_ref_to_entity_id(
            object_ref=object_ref,
            object_type=object_type,
            resolved_mentions=resolved_mentions,
            resolved_context_refs=[],
            catalog_name_index=catalog_name_index,
        )

    def _should_reject_preference_graph_candidate(
        self,
        *,
        event: MemoryEvent,
        subject_id: str,
        predicate: str,
        object_id: str,
        object_type: str,
        raw_object_ref: str,
        evidence_text: str | None = None,
    ) -> bool:
        host = self._graph_validation_host()
        if host._is_address_preference_object(
            event_text=event.content,
            value=raw_object_ref,
        ):
            return True
        if predicate not in _PREFERENCE_PREDICATES:
            return False
        if host._looks_like_interrogative_preference_query(evidence_text if evidence_text is not None else event.content):
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
        return self._resolve_object_ref_to_entity_id(
            object_ref=object_ref,
            object_type=object_type,
            resolved_mentions=resolved_mentions,
            resolved_context_refs=resolved_context_refs,
            catalog_name_index=catalog_name_index,
        )

    def _resolve_object_ref_to_entity_id(
        self,
        *,
        object_ref: str,
        object_type: str,
        resolved_mentions: list[ResolvedEntityMention],
        resolved_context_refs: list[ResolvedContextRef],
        catalog_name_index: dict[str, str] | None,
    ) -> str | None:
        host = self._graph_validation_host()
        lookup_candidates = self._object_ref_lookup_candidates(
            object_ref=object_ref,
            object_type=object_type,
        )

        for candidate in lookup_candidates:
            context_hit = self._lookup_context_ref(candidate, resolved_context_refs)
            if context_hit:
                return context_hit

        for candidate in lookup_candidates:
            mention_hit = self._lookup_resolved_mention(candidate, resolved_mentions)
            if mention_hit:
                return mention_hit

        for candidate in lookup_candidates:
            catalog_hit = self._lookup_catalog_index(candidate, catalog_name_index)
            if catalog_hit:
                return catalog_hit

        catalog_required = self._catalog_resolution_required(catalog_name_index)
        if ":" in object_ref:
            return None if catalog_required else object_ref

        fallback_surface = lookup_candidates[0] if lookup_candidates else object_ref
        if catalog_required:
            return None
        return host._build_concept_node(
            entity_type=object_type,
            normalized_surface=fallback_surface,
        )

    def _catalog_resolution_required(self, catalog_name_index: dict[str, str] | None) -> bool:
        if catalog_name_index is None:
            return False
        host = self._graph_validation_host()
        return getattr(host, "_entity_catalog", None) is not None

    def _object_ref_lookup_candidates(self, *, object_ref: str, object_type: str) -> list[str]:
        candidates: list[str] = []

        def add(value: str | None) -> None:
            text = str(value or "").strip()
            if text and text.casefold() not in {item.casefold() for item in candidates}:
                candidates.append(text)

        if ":" in object_ref:
            prefix, _, suffix = object_ref.partition(":")
            stripped_suffix = self._strip_redundant_type_prefix(
                value=suffix,
                object_type=object_type or prefix,
            )
            add(object_ref)
            add(suffix)
            add(stripped_suffix)
        else:
            stripped_ref = self._strip_redundant_type_prefix(
                value=object_ref,
                object_type=object_type,
            )
            add(stripped_ref)
            add(object_ref)
        return candidates

    def _strip_redundant_type_prefix(self, *, value: str, object_type: str) -> str:
        text = str(value or "").strip()
        normalized_type = str(object_type or "").strip().casefold()
        if not text or not normalized_type:
            return text
        for separator in ("-", "_", ":"):
            marker = f"{normalized_type}{separator}"
            if text.casefold().startswith(marker):
                return text[len(marker):].strip()
        return text

    def _lookup_context_ref(
        self,
        candidate: str,
        resolved_context_refs: list[ResolvedContextRef],
    ) -> str | None:
        candidate_casefold = candidate.casefold()
        for context_ref in resolved_context_refs:
            if (
                context_ref.surface
                and context_ref.resolved_ref
                and context_ref.surface.casefold() == candidate_casefold
            ):
                return str(context_ref.resolved_ref)
        return None

    def _lookup_resolved_mention(
        self,
        candidate: str,
        resolved_mentions: list[ResolvedEntityMention],
    ) -> str | None:
        host = self._graph_validation_host()
        candidate_casefold = candidate.casefold()
        for mention in resolved_mentions:
            resolved_entity_id = host._non_empty_text(mention.resolved_entity_id)
            if not resolved_entity_id:
                continue
            surfaces = {
                mention.mention_text.strip().casefold(),
                mention.normalized_surface.strip().casefold(),
                resolved_entity_id.casefold(),
            }
            if candidate_casefold in surfaces:
                return resolved_entity_id
        return None

    def _lookup_catalog_index(
        self,
        candidate: str,
        catalog_name_index: dict[str, str] | None,
    ) -> str | None:
        if catalog_name_index is None:
            return None
        catalog_hit = catalog_name_index.get(candidate.casefold())
        return str(catalog_hit) if catalog_hit else None

    def _graph_validation_host(self) -> _L2GraphValidationHostProtocol:
        return self  # type: ignore[return-value]


__all__ = ["L2GraphEndpointResolutionMixin"]
