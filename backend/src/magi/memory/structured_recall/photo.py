"""Photo-specific structured recall expansion."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import re
from typing import Any

from ..hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from ..hybrid_retrieval.recall_shape import RecallShape
from ..l1.source_facets import (
    PHOTO_LIBRARY_SOURCE,
    PHOTO_LOCATION_FACETS,
    extract_source_facets,
    normalize_facet_text,
)
from .governance import EventIdBlocklist, exclude_governed_events

PHOTO_QUERY_LOCATION_FACETS = (*PHOTO_LOCATION_FACETS, "photo.retrieval_term")


async def expand_photo_structured_recall(
    *,
    l1_store: Any,
    request: RetrievalQuery,
    recall_shape: RecallShape,
    payload: RetrievalPayload,
    event_id_blocklist: EventIdBlocklist | None = None,
) -> dict[str, Any] | None:
    """Expand a photo seed result into complete source-backed photo stats."""
    if recall_shape.domain_hint != "photo" or recall_shape.desired_coverage != "exhaustive":
        return None
    if l1_store is None or not hasattr(l1_store, "find_events_by_source_facets"):
        return None

    aliases = _seed_location_aliases(payload.l1_events)
    facet_names = list(PHOTO_LOCATION_FACETS)
    if not aliases:
        aliases = _query_location_aliases(request.query)
        facet_names = list(PHOTO_QUERY_LOCATION_FACETS)
    if not aliases:
        return None

    await _ensure_photo_facets(l1_store)
    events = await l1_store.find_events_by_source_facets(
        source=PHOTO_LIBRARY_SOURCE,
        facet_names=facet_names,
        normalized_text_values=sorted(aliases),
        user_id=request.user_id,
        time_start=_coerce_float((request.time_range or {}).get("start")),
        time_end=_coerce_float((request.time_range or {}).get("end")),
        limit=max(int(request.limit or 10) * 20, 1000),
    )
    events = await exclude_governed_events(
        events,
        event_id_blocklist=event_id_blocklist,
    )
    if not events:
        return None

    items = [_event_to_item(event) for event in events]
    total_photos = sum(item["photo_count"] for item in items)
    by_year = Counter(_year_from_timestamp(item["timestamp"]) for item in items)
    by_year.pop(None, None)

    max_items = max(int(request.limit or 10), 20)
    returned_items = items[:max_items]

    return {
        "domain": "photo",
        "operation": recall_shape.operation,
        "title": "Photo structured recall",
        "coverage": {
            "kind": "exhaustive",
            "can_claim_total": True,
            "total_count": len(items),
            "returned_count": len(returned_items),
            "omitted_count": max(len(items) - len(returned_items), 0),
            "scope": {
                "source": PHOTO_LIBRARY_SOURCE,
                "facet_names": facet_names,
                "alias_count": len(aliases),
            },
        },
        "summary": {
            "session_count": len(items),
            "photo_count": total_photos,
            "first_timestamp": min(item["timestamp"] for item in items),
            "last_timestamp": max(item["timestamp"] for item in items),
            "by_year": dict(sorted(by_year.items())),
        },
        "items": returned_items,
    }


async def _ensure_photo_facets(l1_store: Any) -> None:
    count_method = getattr(l1_store, "count_source_facets", None)
    rebuild_method = getattr(l1_store, "rebuild_source_facets", None)
    if not callable(count_method) or not callable(rebuild_method):
        return
    existing = await count_method(source=PHOTO_LIBRARY_SOURCE)
    if existing > 0:
        return
    await rebuild_method(source_filter=PHOTO_LIBRARY_SOURCE)


def _seed_location_aliases(events: list[dict[str, Any]]) -> set[str]:
    aliases: set[str] = set()
    main_aliases: set[str] = set()
    candidate_aliases: set[str] = set()
    for event in events:
        if str(event.get("source") or "") != PHOTO_LIBRARY_SOURCE:
            continue
        main_aliases.update(_main_location_aliases_from_content(str(event.get("content") or "")))
        for facet in extract_source_facets(event):
            if facet.facet_name not in PHOTO_LOCATION_FACETS:
                continue
            normalized = facet.normalized_text_value or normalize_facet_text(facet.text_value)
            if normalized:
                candidate_aliases.add(normalized)
    if main_aliases:
        aliases.update(main_aliases)
        aliases.update(
            alias
            for alias in candidate_aliases
            if _matches_main_location(alias=alias, main_aliases=main_aliases)
        )
        return aliases
    aliases.update(alias for alias in candidate_aliases if _is_selective_alias(alias))
    return aliases


def _main_location_aliases_from_content(content: str) -> set[str]:
    aliases: set[str] = set()
    match = re.search(r"在\s*(.+?)\s*(?:拍摄了|拍了)\s*\d+\s*张", content)
    if not match:
        return aliases
    normalized = normalize_facet_text(match.group(1))
    if normalized:
        aliases.add(normalized)
    return aliases


def _query_location_aliases(query: str) -> set[str]:
    aliases: set[str] = set()
    for candidate in _iter_query_location_candidates(query):
        normalized = normalize_facet_text(candidate)
        if not _is_selective_query_alias(normalized):
            continue
        aliases.add(normalized)
        aliases.update(_known_location_equivalents(normalized))
    return aliases


def _iter_query_location_candidates(query: str) -> list[str]:
    text = str(query or "").strip()
    if not text:
        return []

    candidates: list[str] = []
    patterns = (
        r"(?:在|去|到|于)\s*([^，。！？?、,]{1,48}?)(?:拍|照|照片|相片|图片|$)",
        r"\b(?:in|at|near|around)\s+([a-z][a-z0-9\s.'-]{1,80}?)(?=\s+(?:photo|photos|picture|pictures|shot|shots|take|took|taken|$))",
    )
    for pattern in patterns:
        candidates.extend(match.group(1).strip() for match in re.finditer(pattern, text, re.I))
    return candidates


def _is_selective_query_alias(alias: str) -> bool:
    if not alias or len(alias) < 2:
        return False
    blocked = {
        "照片",
        "图片",
        "相片",
        "什么",
        "什么照片",
        "photo",
        "photos",
        "picture",
        "pictures",
    }
    return alias not in blocked


def _known_location_equivalents(alias: str) -> set[str]:
    equivalents: set[str] = set()
    if alias == "东京" or " tokyo " in f" {alias} " or alias.endswith(" tokyo"):
        equivalents.update({"东京", "tokyo"})
    if alias == "tokyo":
        equivalents.add("东京")
    return equivalents


def _matches_main_location(*, alias: str, main_aliases: set[str]) -> bool:
    if alias in main_aliases:
        return True
    return any(alias.startswith(f"{main} ") for main in main_aliases)


def _is_selective_alias(alias: str) -> bool:
    tokens = alias.split()
    if len(tokens) < 2:
        return False
    if len(tokens) <= 3 and tokens[-1:] == ["china"]:
        return False
    return True


def _event_to_item(event: dict[str, Any]) -> dict[str, Any]:
    photo_count = 1
    for facet in extract_source_facets(event):
        if facet.facet_name == "photo.count" and facet.numeric_value is not None:
            photo_count = max(int(facet.numeric_value), 0)
            break
    return {
        "event_id": str(event.get("event_id") or ""),
        "timestamp": float(event.get("timestamp") or 0.0),
        "source": str(event.get("source") or ""),
        "content": str(event.get("content") or ""),
        "photo_count": photo_count,
        "metadata_json": event.get("metadata_json"),
    }


def _year_from_timestamp(timestamp: float) -> int | None:
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp).year


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["expand_photo_structured_recall"]
