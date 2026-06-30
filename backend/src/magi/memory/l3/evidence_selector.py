"""Source-aware L1 evidence selection for temporal L3 summaries."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..l1.event_store import L1EventStore

SELECTION_POLICY_VERSION = "source_aware_compaction_v1"
DEFAULT_MAX_SELECTED_EVENTS = 120
DEFAULT_MAX_FEATURE_EVENTS_PER_SOURCE = 240
DEFAULT_MIN_EVENTS_PER_SOURCE = 4
DEFAULT_MAX_SUMMARY_LINES_PER_SOURCE = 6
DEFAULT_MAX_REPRESENTATIVE_EVENTS_PER_SOURCE = 8


@dataclass(slots=True)
class TemporalEvidenceSelection:
    """Selected raw events plus source-level coverage metadata."""

    selected_events: list[dict[str, Any]] = field(default_factory=list)
    feature_events: list[dict[str, Any]] = field(default_factory=list)
    feature_budgets: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_distribution: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_event_total: int = 0
    omitted_event_count: int = 0
    selection_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _SourceEvidenceCollection:
    selected_events: list[dict[str, Any]] = field(default_factory=list)
    feature_events: list[dict[str, Any]] = field(default_factory=list)
    feature_budgets: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_distribution: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_source(
        self,
        *,
        source_type: str,
        stats: dict[str, Any],
        total_count: int,
        pool: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        max_feature_events_per_source: int,
    ) -> None:
        self.selected_events.extend(selected)
        self.feature_events.extend(pool)
        self.source_distribution[source_type] = _source_distribution_entry(
            stats,
            selected_event_count=len(selected),
            feature_event_count=len(pool),
        )
        self.feature_budgets[source_type] = _feature_budget(
            source_type=source_type,
            total_event_count=total_count,
            available_event_count=len(pool),
            selected_event_count=len(selected),
            max_feature_events=max_feature_events_per_source,
        )


async def select_temporal_evidence(
    *,
    l1_store: L1EventStore,
    period_start: float,
    period_end: float,
    source_filter: list[str] | None = None,
    max_selected_events: int = DEFAULT_MAX_SELECTED_EVENTS,
    max_feature_events_per_source: int = DEFAULT_MAX_FEATURE_EVENTS_PER_SOURCE,
    min_events_per_source: int = DEFAULT_MIN_EVENTS_PER_SOURCE,
) -> TemporalEvidenceSelection:
    """Build a source-balanced temporal evidence sample from an L1 window."""

    policy = _selection_policy(
        max_selected_events,
        max_feature_events_per_source,
        min_events_per_source,
    )
    source_stats = await _summarize_temporal_sources(
        l1_store=l1_store,
        source_filter=source_filter,
        period_start=period_start,
        period_end=period_end,
    )
    source_event_total = _source_event_total(source_stats)
    if source_event_total <= 0:
        return TemporalEvidenceSelection(selection_policy=policy)

    quotas = _allocate_source_quotas(
        source_stats,
        max_selected_events=max(1, int(max_selected_events)),
        min_events_per_source=max(1, int(min_events_per_source)),
    )
    collection = await _collect_source_evidence(
        l1_store=l1_store,
        source_stats=source_stats,
        quotas=quotas,
        period_start=period_start,
        period_end=period_end,
        max_feature_events_per_source=max_feature_events_per_source,
    )
    return _temporal_evidence_selection(
        collection=collection,
        source_event_total=source_event_total,
        max_selected_events=max_selected_events,
        selection_policy=policy,
    )


async def _summarize_temporal_sources(
    *,
    l1_store: L1EventStore,
    source_filter: list[str] | None,
    period_start: float,
    period_end: float,
) -> list[dict[str, Any]]:
    return await l1_store.summarize_event_sources(
        source_filters=list(source_filter) if source_filter else None,
        cognition_eligible=True,
        start_time=period_start,
        end_time=period_end,
        exclude_memory_domain="runtime_telemetry",
        exclude_retention_class="disposable",
    )


def _source_event_total(source_stats: list[dict[str, Any]]) -> int:
    return sum(int(item.get("event_count") or 0) for item in source_stats)


async def _collect_source_evidence(
    *,
    l1_store: L1EventStore,
    source_stats: list[dict[str, Any]],
    quotas: dict[str, int],
    period_start: float,
    period_end: float,
    max_feature_events_per_source: int,
) -> _SourceEvidenceCollection:
    collection = _SourceEvidenceCollection()
    for stats in source_stats:
        await _collect_source_stats_evidence(
            collection=collection,
            l1_store=l1_store,
            stats=stats,
            quota=int(quotas.get(str(stats.get("source") or "").strip()) or 0),
            period_start=period_start,
            period_end=period_end,
            max_feature_events_per_source=max_feature_events_per_source,
        )
    return collection


async def _collect_source_stats_evidence(
    *,
    collection: _SourceEvidenceCollection,
    l1_store: L1EventStore,
    stats: dict[str, Any],
    quota: int,
    period_start: float,
    period_end: float,
    max_feature_events_per_source: int,
) -> None:
    source_type = str(stats.get("source") or "").strip()
    if not source_type:
        return
    total_count = int(stats.get("event_count") or 0)
    pool: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    if quota > 0:
        pool = await _fetch_source_event_pool(
            l1_store=l1_store,
            source_type=source_type,
            period_start=period_start,
            period_end=period_end,
            quota=quota,
            max_feature_events_per_source=max_feature_events_per_source,
        )
        selected = _select_source_representatives(pool, quota)
    collection.add_source(
        source_type=source_type,
        stats=stats,
        total_count=total_count,
        pool=pool,
        selected=selected,
        max_feature_events_per_source=max_feature_events_per_source,
    )


def _temporal_evidence_selection(
    *,
    collection: _SourceEvidenceCollection,
    source_event_total: int,
    max_selected_events: int,
    selection_policy: dict[str, Any],
) -> TemporalEvidenceSelection:
    selected_events = _sort_events_desc(_dedupe_events(collection.selected_events))[
        :max_selected_events
    ]
    feature_events = _sort_events_desc(_dedupe_events(collection.feature_events))
    omitted_event_count = max(0, source_event_total - len(selected_events))

    return TemporalEvidenceSelection(
        selected_events=selected_events,
        feature_events=feature_events,
        feature_budgets=collection.feature_budgets,
        source_distribution=collection.source_distribution,
        source_event_total=source_event_total,
        omitted_event_count=omitted_event_count,
        selection_policy=selection_policy,
    )


def _allocate_source_quotas(
    source_stats: list[dict[str, Any]],
    *,
    max_selected_events: int,
    min_events_per_source: int,
) -> dict[str, int]:
    counts = {
        str(item.get("source") or "").strip(): int(item.get("event_count") or 0)
        for item in source_stats
        if str(item.get("source") or "").strip() and int(item.get("event_count") or 0) > 0
    }
    if not counts:
        return {}
    total_count = sum(counts.values())
    if total_count <= max_selected_events:
        return dict(counts)

    ordered_sources = sorted(counts, key=lambda source: (-counts[source], source))
    if len(ordered_sources) >= max_selected_events:
        return {
            source: 1 if index < max_selected_events else 0
            for index, source in enumerate(ordered_sources)
        }

    effective_floor = min(
        min_events_per_source, max(1, max_selected_events // len(ordered_sources))
    )
    quotas = {source: min(counts[source], effective_floor) for source in ordered_sources}
    remaining = max_selected_events - sum(quotas.values())
    if remaining <= 0:
        return quotas

    weights = {
        source: math.sqrt(max(0, counts[source] - quotas[source])) for source in ordered_sources
    }
    weight_total = sum(weights.values())
    if weight_total <= 0:
        return quotas

    remainders: list[tuple[float, str]] = []
    for source in ordered_sources:
        raw_share = remaining * (weights[source] / weight_total)
        extra = min(counts[source] - quotas[source], int(raw_share))
        quotas[source] += extra
        remainders.append((raw_share - int(raw_share), source))

    used = sum(quotas.values())
    for _remainder, source in sorted(remainders, reverse=True):
        if used >= max_selected_events:
            break
        if quotas[source] >= counts[source]:
            continue
        quotas[source] += 1
        used += 1
    return quotas


async def _fetch_source_event_pool(
    *,
    l1_store: L1EventStore,
    source_type: str,
    period_start: float,
    period_end: float,
    quota: int,
    max_feature_events_per_source: int,
) -> list[dict[str, Any]]:
    per_query_limit = max(quota * 2, 20)
    per_query_limit = min(max_feature_events_per_source, per_query_limit)
    common_filters = {
        "source_filters": [source_type],
        "cognition_eligible": True,
        "start_time": period_start,
        "end_time": period_end,
        "exclude_memory_domain": "runtime_telemetry",
        "exclude_retention_class": "disposable",
        "include_embedding_fields": False,
    }
    latest_events = await l1_store.query_events(
        **common_filters,
        limit=per_query_limit,
        order_by="timestamp_desc",
    )
    important_events = await l1_store.query_events(
        **common_filters,
        limit=max(quota, min(per_query_limit, quota * 2)),
        order_by="importance_desc",
    )
    earliest_events = await l1_store.query_events(
        **common_filters,
        limit=max(quota, min(per_query_limit, quota * 2)),
        order_by="timestamp_asc",
    )
    return _sort_events_desc(_dedupe_events([*latest_events, *important_events, *earliest_events]))[
        :max_feature_events_per_source
    ]


def _select_source_representatives(
    events: list[dict[str, Any]], quota: int
) -> list[dict[str, Any]]:
    if quota <= 0 or not events:
        return []
    if len(events) <= quota:
        return _sort_events_desc(events)

    selected: list[dict[str, Any]] = []
    recent_count = max(1, int(quota * 0.35))
    important_count = max(1, int(quota * 0.35))
    spread_count = max(0, quota - recent_count - important_count)

    selected.extend(_sort_events_desc(events)[:recent_count])
    selected.extend(_sort_events_by_importance(events)[:important_count])
    selected.extend(_spread_events(events, spread_count))

    deduped = _dedupe_events(selected)
    if len(deduped) < quota:
        deduped.extend(
            event
            for event in _sort_events_by_importance(events)
            if str(event.get("event_id") or "")
            not in {str(item.get("event_id") or "") for item in deduped}
        )
    return _sort_events_desc(_dedupe_events(deduped))[:quota]


def _spread_events(events: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    ordered = sorted(events, key=lambda item: float(item.get("timestamp") or 0.0))
    if len(ordered) <= count:
        return ordered
    if count == 1:
        return [ordered[len(ordered) // 2]]
    return [ordered[round(index * (len(ordered) - 1) / (count - 1))] for index in range(count)]


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        deduped.append(event)
    return deduped


def _sort_events_desc(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda item: float(item.get("timestamp") or 0.0), reverse=True)


def _sort_events_by_importance(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda item: (
            float(item.get("importance_score") or 0.0),
            float(item.get("timestamp") or 0.0),
        ),
        reverse=True,
    )


def _source_distribution_entry(
    stats: dict[str, Any],
    *,
    selected_event_count: int,
    feature_event_count: int,
) -> dict[str, Any]:
    total_event_count = int(stats.get("event_count") or 0)
    return {
        "total_event_count": total_event_count,
        "selected_event_count": int(selected_event_count),
        "feature_event_count": int(feature_event_count),
        "omitted_event_count": max(0, total_event_count - int(selected_event_count)),
        "avg_importance": float(stats.get("avg_importance") or 0.0),
        "min_timestamp": stats.get("min_timestamp"),
        "max_timestamp": stats.get("max_timestamp"),
    }


def _feature_budget(
    *,
    source_type: str,
    total_event_count: int,
    available_event_count: int,
    selected_event_count: int,
    max_feature_events: int,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "total_event_count": int(total_event_count),
        "available_event_count": int(available_event_count),
        "selected_event_count": int(selected_event_count),
        "omitted_event_count": max(0, int(total_event_count) - int(available_event_count)),
        "max_feature_events": int(max_feature_events),
        "max_summary_lines": DEFAULT_MAX_SUMMARY_LINES_PER_SOURCE,
        "max_representative_events": DEFAULT_MAX_REPRESENTATIVE_EVENTS_PER_SOURCE,
        "selection_policy": SELECTION_POLICY_VERSION,
    }


def _selection_policy(
    max_selected_events: int,
    max_feature_events_per_source: int,
    min_events_per_source: int,
) -> dict[str, Any]:
    return {
        "version": SELECTION_POLICY_VERSION,
        "max_selected_events": int(max_selected_events),
        "max_feature_events_per_source": int(max_feature_events_per_source),
        "min_events_per_source": int(min_events_per_source),
        "quota_strategy": "per_source_floor_plus_sqrt_weighted_remainder",
        "representative_strategy": "recent_plus_importance_plus_time_spread",
    }
