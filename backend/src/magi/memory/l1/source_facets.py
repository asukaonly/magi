"""L1 source facet extraction and query helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import time
import unicodedata
from typing import Any, Iterable, Protocol, cast
from urllib.parse import urlparse

from magi.events.source_activity_snapshot import activity_snapshot_from_metadata

from ..event_contracts import MemoryEvent
from .ports import MemoryEventRecord, MemoryEventRepository

from magi_plugin_sdk.storage_models.source_facets import (
    PHOTO_LIBRARY_SOURCE,
    PHOTO_LOCATION_FACETS,
    BROWSER_SOURCES,
    MUSIC_SOURCES,
    _GENERIC_PHOTO_TERMS,
    SourceFacet,
    _FacetContext,
    _L1SourceFacetHostProtocol,
    normalize_facet_text,
    extract_source_facets,
    _extract_contract_source_facets,
    _extract_photo_source_facets,
    _extract_photo_count_facet,
    _extract_photo_device_facet,
    _extract_representative_photo_facets,
    _extract_representative_photo_location_facets,
    _extract_representative_photo_asset_facets,
    _extract_representative_photo_coordinate_facets,
    _extract_photo_retrieval_term_facets,
    _extract_browser_source_facets,
    _extract_music_source_facets,
    _music_text_facets,
    _music_alias_facets,
    _music_metric_facets,
    _music_track_fallback_facets,
    _metadata_from_event_dict,
    _text_facet,
    _context_text_facet,
    _extract_photo_count,
    _extract_device,
    _iter_representative_photos,
    _iter_retrieval_terms,
    _provenance_from_metadata,
    _first_text,
    _first_float,
    _domain_from_url,
    _browser_title_from_content,
    _music_track_from_content,
    _iter_track_aliases,
    _clean_text,
    _coerce_float,
    _dedupe_facets,
)


class L1SourceFacetMixin:
    """Extract facets in memory policy and delegate persistence to its owner."""

    async def list_source_facets(
        self,
        *,
        event_id: str | None = None,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str] | None = None,
        normalized_text_values: list[str] | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        host = cast(_L1SourceFacetHostProtocol, self)
        await host.initialize()
        facets = await host.event_repository.list_source_facets(event_id=event_id, source=source, sources=sources, facet_names=facet_names, normalized_text_values=normalized_text_values, limit=limit)
        return [asdict(facet) for facet in facets]

    async def count_source_facets(
        self,
        *,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str] | None = None,
    ) -> int:
        host = cast(_L1SourceFacetHostProtocol, self)
        await host.initialize()
        return await host.event_repository.count_source_facets(source=source, sources=sources, facet_names=facet_names)

    async def find_events_by_source_facets(
        self,
        *,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str],
        normalized_text_values: list[str],
        user_id: str | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        host = cast(_L1SourceFacetHostProtocol, self)
        await host.initialize()
        records = await host.event_repository.find_events_by_source_facets(source=source, sources=sources, facet_names=facet_names, normalized_text_values=normalized_text_values, user_id=user_id, time_start=time_start, time_end=time_end, limit=limit)
        try:
            active_profile = host._resolve_active_embedding_profile_id()[0]
        except Exception:
            active_profile = None
        return [host._record_to_dict(record, active_embedding_profile_id=active_profile) for record in records]

    async def rebuild_source_facets(
        self,
        *,
        source_filter: str | None = None,
        batch_size: int = 500,
        limit: int | None = None,
    ) -> dict[str, int]:
        host = cast(_L1SourceFacetHostProtocol, self)
        await host.initialize()
        return await host.event_repository.rebuild_source_facets(source_filter=source_filter, batch_size=batch_size, limit=limit)


__all__ = [
    "BROWSER_SOURCES",
    "MUSIC_SOURCES",
    "PHOTO_LIBRARY_SOURCE",
    "PHOTO_LOCATION_FACETS",
    "L1SourceFacetMixin",
    "SourceFacet",
    "extract_source_facets",
    "normalize_facet_text",
]
