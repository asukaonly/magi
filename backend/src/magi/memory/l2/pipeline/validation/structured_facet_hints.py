"""Structured facet candidate conversion for L2 extraction."""

from __future__ import annotations

from typing import Any

from ....event_contracts import MemoryEvent
from ...models import StructuredGraphHint
from ...storage.utils import normalize_event_ids
from .structured_hint_common import (
    L2StructuredHintHostMixin,
    _STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES,
)


class L2StructuredFacetHintMixin(L2StructuredHintHostMixin):
    """Convert source-owned structured graph hint attributes into entity facets."""

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
                        "evidence_event_ids": normalize_event_ids(
                            evidence_event_ids or [event.event_id]
                        ),
                        "confidence": float(
                            hint.confidence if hint.confidence is not None else 1.0
                        ),
                        "observed_at": event.timestamp,
                        "source_type": event.source,
                        "extraction_method": "structured_hint",
                    }
                )
        return prepared


__all__ = ["L2StructuredFacetHintMixin"]
