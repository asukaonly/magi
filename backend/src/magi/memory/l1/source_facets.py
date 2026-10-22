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

PHOTO_LIBRARY_SOURCE = "photo_library_apple_photos"
PHOTO_LOCATION_FACETS = ("photo.location_name", "photo.location_alias")
BROWSER_SOURCES = (
    "browser_history",
    "chrome_history",
    "safari_history",
    "edge_history",
    "firefox_history",
)
MUSIC_SOURCES = ("netease_music", "system_media")

_GENERIC_PHOTO_TERMS = {
    "photo_library",
    "photos",
    "photo",
    "session",
    "geo",
    "location",
}


@dataclass(frozen=True)
class SourceFacet:
    event_id: str
    source: str
    facet_name: str
    text_value: str | None = None
    normalized_text_value: str | None = None
    numeric_value: float | None = None
    timestamp_value: float | None = None
    json_value: str | None = None
    created_at: float = 0.0



@dataclass(frozen=True)
class _FacetContext:
    event_id: str
    source: str
    created_at: float


class _L1SourceFacetHostProtocol(Protocol):
    event_repository: MemoryEventRepository

    async def initialize(self) -> None: ...

    def _record_to_dict(self, record: MemoryEventRecord, **kwargs: Any) -> dict[str, Any]: ...

    def _resolve_active_embedding_profile_id(self) -> tuple[str | None, dict[str, Any]]: ...


def normalize_facet_text(value: str | None) -> str:
    """Normalize source text for exact-ish facet lookup."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_source_facets(event: MemoryEvent | dict[str, Any]) -> list[SourceFacet]:
    """Extract rebuildable source facets from an L1 event."""
    event_dict = event.to_dict() if isinstance(event, MemoryEvent) else dict(event)
    event_id = str(event_dict.get("event_id") or "").strip()
    if not event_id:
        return []
    metadata = _metadata_from_event_dict(event_dict)
    source = str(event_dict.get("source") or metadata.get("source") or "").strip()
    content = str(event_dict.get("content") or "")
    created_at = time.time()
    facets = _extract_contract_source_facets(
        event_id=event_id,
        source=source,
        metadata=metadata,
        created_at=created_at,
    )

    if source == PHOTO_LIBRARY_SOURCE:
        facets.extend(
            _extract_photo_source_facets(
                event_id=event_id,
                source=source,
                content=content,
                metadata=metadata,
                created_at=created_at,
            )
        )
    elif source in BROWSER_SOURCES:
        facets.extend(
            _extract_browser_source_facets(
                event_id=event_id,
                source=source,
                content=content,
                metadata=metadata,
                created_at=created_at,
            )
        )
    elif source in MUSIC_SOURCES:
        facets.extend(
            _extract_music_source_facets(
                event_id=event_id,
                source=source,
                content=content,
                metadata=metadata,
                created_at=created_at,
            )
        )

    return _dedupe_facets(facets)


def _extract_contract_source_facets(
    *,
    event_id: str,
    source: str,
    metadata: dict[str, Any],
    created_at: float,
) -> list[SourceFacet]:
    raw_facets = metadata.get("source_facets")
    if isinstance(raw_facets, dict):
        raw_facets = [raw_facets]
    if not isinstance(raw_facets, list):
        return []

    facets: list[SourceFacet] = []
    for raw in raw_facets:
        if not isinstance(raw, dict):
            continue
        facet_name = _clean_text(raw.get("name") or raw.get("facet_name"))
        if not facet_name:
            continue
        text_value = _clean_text(raw.get("text") if "text" in raw else raw.get("text_value"))
        numeric_value = _coerce_float(
            raw.get("numeric") if "numeric" in raw else raw.get("numeric_value")
        )
        timestamp_value = _coerce_float(
            raw.get("timestamp") if "timestamp" in raw else raw.get("timestamp_value")
        )
        json_value = raw.get("json") if "json" in raw else raw.get("json_value")
        if json_value is not None and not isinstance(json_value, str):
            json_value = json.dumps(json_value, ensure_ascii=False, sort_keys=True)
        json_text = _clean_text(json_value)
        if (
            text_value is None
            and numeric_value is None
            and timestamp_value is None
            and json_text is None
        ):
            continue
        facets.append(
            SourceFacet(
                event_id=event_id,
                source=source,
                facet_name=facet_name,
                text_value=text_value,
                normalized_text_value=normalize_facet_text(text_value) or None,
                numeric_value=numeric_value,
                timestamp_value=timestamp_value,
                json_value=json_text,
                created_at=created_at,
            )
        )
    return facets


def _extract_photo_source_facets(
    *,
    event_id: str,
    source: str,
    content: str,
    metadata: dict[str, Any],
    created_at: float,
) -> list[SourceFacet]:
    context = _FacetContext(event_id=event_id, source=source, created_at=created_at)
    facets: list[SourceFacet] = []
    facets.extend(_extract_photo_count_facet(context=context, content=content, metadata=metadata))
    facets.extend(_extract_photo_device_facet(context=context, content=content, metadata=metadata))
    facets.extend(_extract_representative_photo_facets(context=context, metadata=metadata))
    facets.extend(_extract_photo_retrieval_term_facets(context=context, metadata=metadata))
    return facets


def _extract_photo_count_facet(
    *,
    context: _FacetContext,
    content: str,
    metadata: dict[str, Any],
) -> list[SourceFacet]:
    photo_count = _extract_photo_count(content=content, metadata=metadata)
    if photo_count is None:
        return []
    return [
        SourceFacet(
            event_id=context.event_id,
            source=context.source,
            facet_name="photo.count",
            numeric_value=float(photo_count),
            created_at=context.created_at,
        )
    ]


def _extract_photo_device_facet(
    *,
    context: _FacetContext,
    content: str,
    metadata: dict[str, Any],
) -> list[SourceFacet]:
    device = _extract_device(content=content, metadata=metadata)
    if not device:
        return []
    return [
        _context_text_facet(
            context=context,
            facet_name="photo.device",
            value=device,
        )
    ]


def _extract_representative_photo_facets(
    *,
    context: _FacetContext,
    metadata: dict[str, Any],
) -> list[SourceFacet]:
    facets: list[SourceFacet] = []
    for photo in _iter_representative_photos(metadata):
        facets.extend(_extract_representative_photo_location_facets(context, photo))
        facets.extend(_extract_representative_photo_asset_facets(context, photo))
        facets.extend(_extract_representative_photo_coordinate_facets(context, photo))
    return facets


def _extract_representative_photo_location_facets(
    context: _FacetContext,
    photo: dict[str, Any],
) -> list[SourceFacet]:
    facets: list[SourceFacet] = []
    for key in ("location_name", "apple_photos_place_name"):
        value = _clean_text(photo.get(key))
        if value:
            facets.append(
                _context_text_facet(
                    context=context,
                    facet_name="photo.location_name",
                    value=value,
                )
            )
    for key in ("apple_photos_place_address", "place_address", "address"):
        value = _clean_text(photo.get(key))
        if value:
            facets.append(
                _context_text_facet(
                    context=context,
                    facet_name="photo.location_alias",
                    value=value,
                )
            )
    return facets


def _extract_representative_photo_asset_facets(
    context: _FacetContext,
    photo: dict[str, Any],
) -> list[SourceFacet]:
    asset_id = _clean_text(photo.get("asset_local_id") or photo.get("local_identifier"))
    if not asset_id:
        return []
    return [
        _context_text_facet(
            context=context,
            facet_name="photo.asset_id",
            value=asset_id,
        )
    ]


def _extract_representative_photo_coordinate_facets(
    context: _FacetContext,
    photo: dict[str, Any],
) -> list[SourceFacet]:
    facets: list[SourceFacet] = []
    for key, facet_name in (
        ("latitude", "photo.latitude"),
        ("longitude", "photo.longitude"),
    ):
        numeric = _coerce_float(photo.get(key))
        if numeric is not None:
            facets.append(
                SourceFacet(
                    event_id=context.event_id,
                    source=context.source,
                    facet_name=facet_name,
                    numeric_value=numeric,
                    created_at=context.created_at,
                )
            )
    return facets


def _extract_photo_retrieval_term_facets(
    *,
    context: _FacetContext,
    metadata: dict[str, Any],
) -> list[SourceFacet]:
    facets: list[SourceFacet] = []
    for term in _iter_retrieval_terms(metadata):
        normalized = normalize_facet_text(term)
        if not normalized or normalized in _GENERIC_PHOTO_TERMS:
            continue
        facets.append(
            _context_text_facet(
                context=context,
                facet_name="photo.retrieval_term",
                value=term,
            )
        )
    return facets


def _extract_browser_source_facets(
    *,
    event_id: str,
    source: str,
    content: str,
    metadata: dict[str, Any],
    created_at: float,
) -> list[SourceFacet]:
    provenance = _provenance_from_metadata(metadata)
    url = _first_text(metadata, provenance, keys=("canonical_url", "url"))
    domain = _first_text(metadata, provenance, keys=("domain", "promotion_key"))
    if not domain and url:
        domain = _domain_from_url(url)
    title = _first_text(metadata, provenance, keys=("title",))
    if not title:
        title = _browser_title_from_content(content)
    visit_count = _first_float(metadata, provenance, keys=("merged_visit_count", "visit_count"))

    facets: list[SourceFacet] = []
    if domain:
        facets.append(
            _text_facet(
                event_id=event_id,
                source=source,
                facet_name="browser.domain",
                value=domain,
                created_at=created_at,
            )
        )
    if title:
        facets.append(
            _text_facet(
                event_id=event_id,
                source=source,
                facet_name="browser.title",
                value=title,
                created_at=created_at,
            )
        )
    if url:
        facets.append(
            _text_facet(
                event_id=event_id,
                source=source,
                facet_name="browser.url",
                value=url,
                created_at=created_at,
            )
        )
    facets.append(
        SourceFacet(
            event_id=event_id,
            source=source,
            facet_name="browser.visit_count",
            numeric_value=max(float(visit_count or 1.0), 1.0),
            created_at=created_at,
        )
    )
    return facets


def _extract_music_source_facets(
    *,
    event_id: str,
    source: str,
    content: str,
    metadata: dict[str, Any],
    created_at: float,
) -> list[SourceFacet]:
    provenance = _provenance_from_metadata(metadata)
    facets = _music_text_facets(
        event_id=event_id,
        source=source,
        metadata=metadata,
        provenance=provenance,
        created_at=created_at,
    )
    facets.extend(
        _music_alias_facets(
            event_id=event_id,
            source=source,
            metadata=metadata,
            provenance=provenance,
            created_at=created_at,
        )
    )
    facets.extend(
        _music_metric_facets(
            event_id=event_id,
            source=source,
            metadata=metadata,
            provenance=provenance,
            created_at=created_at,
        )
    )
    facets.extend(
        _music_track_fallback_facets(
            event_id=event_id,
            source=source,
            content=content,
            existing_facets=facets,
            created_at=created_at,
        )
    )
    return facets


def _music_text_facets(
    *,
    event_id: str,
    source: str,
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    created_at: float,
) -> list[SourceFacet]:
    field_pairs = (
        (("track_name", "title"), "music.track"),
        (("artist_name", "artist"), "music.artist"),
        (("album_name", "album"), "music.album"),
        (("track_id",), "music.track_id"),
        (("artist_id",), "music.artist_id"),
        (("album_id",), "music.album_id"),
        (("app_name", "app_id"), "music.app"),
    )
    facets: list[SourceFacet] = []
    for keys, facet_name in field_pairs:
        value = _first_text(metadata, provenance, keys=keys)
        if not value:
            continue
        facets.append(
            _text_facet(
                event_id=event_id,
                source=source,
                facet_name=facet_name,
                value=value,
                created_at=created_at,
            )
        )
    return facets


def _music_alias_facets(
    *,
    event_id: str,
    source: str,
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    created_at: float,
) -> list[SourceFacet]:
    facets: list[SourceFacet] = []
    for alias in _iter_track_aliases(metadata, provenance):
        facets.append(
            _text_facet(
                event_id=event_id,
                source=source,
                facet_name="music.track_alias",
                value=alias,
                created_at=created_at,
            )
        )
    return facets


def _music_metric_facets(
    *,
    event_id: str,
    source: str,
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    created_at: float,
) -> list[SourceFacet]:
    duration = _first_float(metadata, provenance, keys=("play_duration_sec", "duration_seconds"))
    facets = [
        SourceFacet(
            event_id=event_id,
            source=source,
            facet_name="music.play_count",
            numeric_value=1.0,
            created_at=created_at,
        )
    ]
    if duration is not None:
        facets.append(
            SourceFacet(
                event_id=event_id,
                source=source,
                facet_name="music.play_duration_sec",
                numeric_value=max(duration, 0.0),
                created_at=created_at,
            )
        )
    return facets


def _music_track_fallback_facets(
    *,
    event_id: str,
    source: str,
    content: str,
    existing_facets: list[SourceFacet],
    created_at: float,
) -> list[SourceFacet]:
    if any(facet.facet_name == "music.track" for facet in existing_facets):
        return []
    parsed_track = _music_track_from_content(content)
    if not parsed_track:
        return []
    return [
        _text_facet(
            event_id=event_id,
            source=source,
            facet_name="music.track",
            value=parsed_track,
            created_at=created_at,
        )
    ]


def _metadata_from_event_dict(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata_json")
    if metadata is None:
        metadata = event.get("metadata")
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return metadata if isinstance(metadata, dict) else {}


def _text_facet(
    *,
    event_id: str,
    source: str,
    facet_name: str,
    value: str,
    created_at: float,
) -> SourceFacet:
    normalized = normalize_facet_text(value)
    return SourceFacet(
        event_id=event_id,
        source=source,
        facet_name=facet_name,
        text_value=value,
        normalized_text_value=normalized or None,
        created_at=created_at,
    )


def _context_text_facet(
    *,
    context: _FacetContext,
    facet_name: str,
    value: str,
) -> SourceFacet:
    return _text_facet(
        event_id=context.event_id,
        source=context.source,
        facet_name=facet_name,
        value=value,
        created_at=context.created_at,
    )


def _extract_photo_count(*, content: str, metadata: dict[str, Any]) -> int | None:
    for key in ("photo_count", "asset_count", "count", "session_photo_count"):
        numeric = _coerce_float(metadata.get(key))
        if numeric is not None and numeric >= 0:
            return int(numeric)
    for pattern in (
        r"(?:拍摄了|拍了)\s*(\d+)\s*张",
        r"(\d+)\s*(?:张照片|photos?)",
    ):
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_device(*, content: str, metadata: dict[str, Any]) -> str | None:
    for key in ("device", "camera_model", "model"):
        value = _clean_text(metadata.get(key))
        if value:
            return value
    match = re.search(r"用\s+(.+?)\s+在", content)
    return _clean_text(match.group(1)) if match else None


def _iter_representative_photos(metadata: dict[str, Any]) -> Iterable[dict[str, Any]]:
    photos = metadata.get("representative_photos")
    if isinstance(photos, dict):
        photos = [photos]
    if isinstance(photos, list):
        for photo in photos:
            if isinstance(photo, dict):
                yield photo


def _iter_retrieval_terms(metadata: dict[str, Any]) -> Iterable[str]:
    projection = metadata.get("projection")
    if not isinstance(projection, dict):
        return []
    terms = projection.get("retrieval_terms")
    if not isinstance(terms, list):
        return []
    return [str(term).strip() for term in terms if str(term).strip()]


def _provenance_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    activity_snapshot = activity_snapshot_from_metadata(metadata)
    provenance = activity_snapshot.get("provenance")
    return provenance if isinstance(provenance, dict) else {}


def _first_text(
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    *,
    keys: tuple[str, ...],
) -> str | None:
    for container in (metadata, provenance):
        for key in keys:
            value = _clean_text(container.get(key))
            if value:
                return value
    return None


def _first_float(
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    *,
    keys: tuple[str, ...],
) -> float | None:
    for container in (metadata, provenance):
        for key in keys:
            value = _coerce_float(container.get(key))
            if value is not None:
                return value
    return None


def _domain_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        return host[4:]
    return host or None


def _browser_title_from_content(content: str) -> str | None:
    match = re.search(
        r"(?:visited|viewed|浏览|访问)\s+(.+?)(?:[。.\n]|$)", content, flags=re.IGNORECASE
    )
    return _clean_text(match.group(1)) if match else None


def _music_track_from_content(content: str) -> str | None:
    quoted = re.search(r"[《']([^》']+)[》']", content)
    if quoted:
        return _clean_text(quoted.group(1))
    match = re.search(r"listened to\s+(.+?)(?:\s+by\s+|[。.\n]|$)", content, flags=re.IGNORECASE)
    return _clean_text(match.group(1)) if match else None


def _iter_track_aliases(metadata: dict[str, Any], provenance: dict[str, Any]) -> Iterable[str]:
    for container in (metadata, provenance):
        aliases = container.get("track_alias")
        if isinstance(aliases, str):
            aliases = [aliases]
        if isinstance(aliases, list):
            for alias in aliases:
                value = _clean_text(alias)
                if value:
                    yield value


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_facets(facets: list[SourceFacet]) -> list[SourceFacet]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[SourceFacet] = []
    for facet in facets:
        key = (
            facet.event_id,
            facet.source,
            facet.facet_name,
            facet.normalized_text_value,
            facet.numeric_value,
            facet.timestamp_value,
            facet.json_value,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(facet)
    return unique


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
