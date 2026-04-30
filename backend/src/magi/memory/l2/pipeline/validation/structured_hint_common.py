"""Shared contracts and constants for structured L2 hints."""

from __future__ import annotations

from typing import Any, Optional, Protocol

from ....event_contracts import MemoryEvent
from ...models import ResolvedEntityMention

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


class L2StructuredHintHostMixin:
    """Provide the shared structured-hint host cast."""

    def _structured_hint_host(self) -> _L2StructuredHintHostProtocol:
        return self  # type: ignore[return-value]


__all__ = [
    "L2StructuredHintHostMixin",
    "_L2StructuredHintHostProtocol",
    "_STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS",
    "_STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES",
    "_STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS",
]
