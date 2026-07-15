"""Generic source-facet structured recall expansion."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from ..hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from ..hybrid_retrieval.recall_shape import RecallShape
from ..l1.source_facets import (
    BROWSER_SOURCES,
    MUSIC_SOURCES,
    extract_source_facets,
    normalize_facet_text,
)
from .governance import EventIdBlocklist, exclude_governed_events


@dataclass(frozen=True)
class _StructuredRecallSpec:
    domain: str
    sources: tuple[str, ...]
    seed_facet_names: tuple[str, ...]
    metric_facet_name: str
    metric_label: str
    default_metric_value: float = 1.0
    duration_facet_name: str | None = None


_SPECS: dict[str, _StructuredRecallSpec] = {
    "browser": _StructuredRecallSpec(
        domain="browser",
        sources=BROWSER_SOURCES,
        seed_facet_names=("browser.domain",),
        metric_facet_name="browser.visit_count",
        metric_label="visits",
    ),
    "music": _StructuredRecallSpec(
        domain="music",
        sources=MUSIC_SOURCES,
        seed_facet_names=("music.track", "music.track_alias", "music.artist", "music.album"),
        metric_facet_name="music.play_count",
        metric_label="plays",
        duration_facet_name="music.play_duration_sec",
    ),
}


async def expand_generic_structured_recall(
    *,
    l1_store: Any,
    request: RetrievalQuery,
    recall_shape: RecallShape,
    payload: RetrievalPayload,
    event_id_blocklist: EventIdBlocklist | None = None,
) -> dict[str, Any] | None:
    """Expand a seed result into complete source-facet-backed stats."""
    spec = _eligible_structured_recall_spec(
        l1_store=l1_store,
        recall_shape=recall_shape,
    )
    if spec is None:
        return None

    seed = _structured_recall_seed(spec=spec, payload=payload, query=request.query)
    if seed is None:
        return None

    await _ensure_source_facets(l1_store, spec=spec)
    events = await _find_structured_recall_events(
        l1_store=l1_store,
        spec=spec,
        seed=seed,
        request=request,
    )
    events = await exclude_governed_events(
        events,
        event_id_blocklist=event_id_blocklist,
    )
    if not events:
        return None

    return _build_structured_recall_result(
        spec=spec,
        recall_shape=recall_shape,
        request=request,
        seed=seed,
        events=events,
    )


def _eligible_structured_recall_spec(
    *,
    l1_store: Any,
    recall_shape: RecallShape,
) -> _StructuredRecallSpec | None:
    spec = _SPECS.get(recall_shape.domain_hint)
    if spec is None or recall_shape.desired_coverage != "exhaustive":
        return None
    if l1_store is None or not hasattr(l1_store, "find_events_by_source_facets"):
        return None
    return spec


def _structured_recall_seed(
    *,
    spec: _StructuredRecallSpec,
    payload: RetrievalPayload,
    query: str,
) -> dict[str, Any] | None:
    seed = _select_seed(spec=spec, payload=payload, query=query)
    if seed is None and spec.domain == "browser":
        return _browser_seed_from_query(query)
    return seed


async def _find_structured_recall_events(
    *,
    l1_store: Any,
    spec: _StructuredRecallSpec,
    seed: dict[str, Any],
    request: RetrievalQuery,
) -> list[dict[str, Any]]:
    return await l1_store.find_events_by_source_facets(
        sources=list(spec.sources),
        facet_names=[seed["facet_name"]],
        normalized_text_values=sorted(seed["aliases"]),
        user_id=request.user_id,
        time_start=_coerce_float((request.time_range or {}).get("start")),
        time_end=_coerce_float((request.time_range or {}).get("end")),
        limit=max(int(request.limit or 10) * 50, 1000),
    )


def _build_structured_recall_result(
    *,
    spec: _StructuredRecallSpec,
    recall_shape: RecallShape,
    request: RetrievalQuery,
    seed: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    items = [_event_to_item(event, spec=spec) for event in events]
    max_items = max(int(request.limit or 10), 20)
    returned_items = items[:max_items]
    return {
        "domain": spec.domain,
        "operation": recall_shape.operation,
        "title": f"{spec.domain.title()} structured recall",
        "coverage": _structured_recall_coverage(spec, seed, items, returned_items),
        "summary": _structured_recall_summary(spec, seed, items),
        "items": returned_items,
    }


def _structured_recall_summary(
    spec: _StructuredRecallSpec,
    seed: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    by_year = Counter(_year_from_timestamp(item["timestamp"]) for item in items)
    by_year.pop(None, None)
    metric_total = sum(float(item["metric_value"]) for item in items)
    summary: dict[str, Any] = {
        "event_count": len(items),
        "metric_label": spec.metric_label,
        "metric_total": _clean_number(metric_total),
        "first_timestamp": min(item["timestamp"] for item in items),
        "last_timestamp": max(item["timestamp"] for item in items),
        "by_year": dict(sorted(by_year.items())),
        "scope_label": seed.get("label") or "",
    }
    if spec.duration_facet_name:
        duration_total = sum(float(item.get("duration_sec") or 0.0) for item in items)
        summary["duration_total_sec"] = _clean_number(duration_total)
    return summary


def _structured_recall_coverage(
    spec: _StructuredRecallSpec,
    seed: dict[str, Any],
    items: list[dict[str, Any]],
    returned_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "kind": "exhaustive",
        "can_claim_total": True,
        "total_count": len(items),
        "returned_count": len(returned_items),
        "omitted_count": max(len(items) - len(returned_items), 0),
        "scope": {
            "sources": list(spec.sources),
            "facet_name": seed["facet_name"],
            "alias_count": len(seed["aliases"]),
        },
    }


async def _ensure_source_facets(l1_store: Any, *, spec: _StructuredRecallSpec) -> None:
    count_method = getattr(l1_store, "count_source_facets", None)
    rebuild_method = getattr(l1_store, "rebuild_source_facets", None)
    if not callable(count_method) or not callable(rebuild_method):
        return
    existing = await count_method(sources=list(spec.sources))
    if existing > 0:
        return
    for source in spec.sources:
        await rebuild_method(source_filter=source)


def _select_seed(
    *,
    spec: _StructuredRecallSpec,
    payload: RetrievalPayload,
    query: str,
) -> dict[str, Any] | None:
    query_norm = normalize_facet_text(query)
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for event in payload.l1_events:
        if str(event.get("source") or "") not in spec.sources:
            continue
        for facet in extract_source_facets(event):
            if facet.facet_name not in spec.seed_facet_names:
                continue
            normalized = facet.normalized_text_value or normalize_facet_text(facet.text_value)
            if not normalized:
                continue
            key = (facet.facet_name, normalized)
            existing = candidates.setdefault(
                key,
                {
                    "facet_name": facet.facet_name,
                    "normalized": normalized,
                    "label": facet.text_value or normalized,
                    "count": 0,
                },
            )
            existing["count"] += 1

    if not candidates:
        return None

    best = max(
        candidates.values(),
        key=lambda item: _seed_score(spec=spec, item=item, query_norm=query_norm),
    )
    return {
        "facet_name": best["facet_name"],
        "aliases": {best["normalized"]},
        "label": best["label"],
    }


def _seed_score(
    *, spec: _StructuredRecallSpec, item: dict[str, Any], query_norm: str
) -> tuple[int, int, int]:
    normalized = str(item["normalized"])
    facet_name = str(item["facet_name"])
    query_match = 1 if normalized and normalized in query_norm else 0
    repeat_count = int(item["count"])
    try:
        preference = len(spec.seed_facet_names) - spec.seed_facet_names.index(facet_name)
    except ValueError:
        preference = 0
    return (query_match, repeat_count, preference)


def _browser_seed_from_query(query: str) -> dict[str, Any] | None:
    match = re.search(r"\b([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]+)+)\b", query, re.I)
    if not match:
        return None
    domain = match.group(1).casefold()
    if domain.startswith("www."):
        domain = domain[4:]
    return {
        "facet_name": "browser.domain",
        "aliases": {normalize_facet_text(domain)},
        "label": domain,
    }


def _event_to_item(event: dict[str, Any], *, spec: _StructuredRecallSpec) -> dict[str, Any]:
    metric_value = spec.default_metric_value
    duration_sec = 0.0
    for facet in extract_source_facets(event):
        if facet.facet_name == spec.metric_facet_name and facet.numeric_value is not None:
            metric_value = max(float(metric_value), float(facet.numeric_value))
        elif (
            spec.duration_facet_name
            and facet.facet_name == spec.duration_facet_name
            and facet.numeric_value is not None
        ):
            duration_sec = max(float(duration_sec), float(facet.numeric_value))
    item: dict[str, Any] = {
        "event_id": str(event.get("event_id") or ""),
        "timestamp": float(event.get("timestamp") or 0.0),
        "source": str(event.get("source") or ""),
        "content": str(event.get("content") or ""),
        "metric_value": _clean_number(metric_value),
        "metadata_json": event.get("metadata_json"),
    }
    if spec.duration_facet_name:
        item["duration_sec"] = _clean_number(duration_sec)
    return item


def _year_from_timestamp(timestamp: float) -> int | None:
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp).year


def _clean_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["expand_generic_structured_recall"]
