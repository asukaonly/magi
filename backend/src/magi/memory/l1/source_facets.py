"""L1 source facet extraction and query helpers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol, cast

from .ports import MemoryEventRecord, MemoryEventRepository

from magi_plugin_sdk.storage_models.source_facets import (
    PHOTO_LIBRARY_SOURCE,
    PHOTO_LOCATION_FACETS,
    BROWSER_SOURCES,
    MUSIC_SOURCES,
    _GENERIC_PHOTO_TERMS as _GENERIC_PHOTO_TERMS,
    SourceFacet,
    _FacetContext as _FacetContext,
    normalize_facet_text,
    extract_source_facets,
    _extract_contract_source_facets as _extract_contract_source_facets,
    _extract_photo_source_facets as _extract_photo_source_facets,
    _extract_photo_count_facet as _extract_photo_count_facet,
    _extract_photo_device_facet as _extract_photo_device_facet,
    _extract_representative_photo_facets as _extract_representative_photo_facets,
    _extract_representative_photo_location_facets as _extract_representative_photo_location_facets,
    _extract_representative_photo_asset_facets as _extract_representative_photo_asset_facets,
    _extract_representative_photo_coordinate_facets as _extract_representative_photo_coordinate_facets,
    _extract_photo_retrieval_term_facets as _extract_photo_retrieval_term_facets,
    _extract_browser_source_facets as _extract_browser_source_facets,
    _extract_music_source_facets as _extract_music_source_facets,
    _music_text_facets as _music_text_facets,
    _music_alias_facets as _music_alias_facets,
    _music_metric_facets as _music_metric_facets,
    _music_track_fallback_facets as _music_track_fallback_facets,
    _metadata_from_event_dict as _metadata_from_event_dict,
    _text_facet as _text_facet,
    _context_text_facet as _context_text_facet,
    _extract_photo_count as _extract_photo_count,
    _extract_device as _extract_device,
    _iter_representative_photos as _iter_representative_photos,
    _iter_retrieval_terms as _iter_retrieval_terms,
    _provenance_from_metadata as _provenance_from_metadata,
    _first_text as _first_text,
    _first_float as _first_float,
    _domain_from_url as _domain_from_url,
    _browser_title_from_content as _browser_title_from_content,
    _music_track_from_content as _music_track_from_content,
    _iter_track_aliases as _iter_track_aliases,
    _clean_text as _clean_text,
    _coerce_float as _coerce_float,
    _dedupe_facets as _dedupe_facets,
)

class _L1SourceFacetHostProtocol(Protocol):
    event_repository: MemoryEventRepository

    async def initialize(self) -> None: ...

    def _record_to_dict(self, record: MemoryEventRecord, **kwargs: Any) -> dict[str, Any]: ...

    def _resolve_active_embedding_profile_id(self) -> tuple[str | None, dict[str, Any]]: ...


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
