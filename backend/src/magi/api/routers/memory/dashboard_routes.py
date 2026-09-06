"""Memory dashboard API route."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Query, status

from magi.memory.event_contracts import RetentionClass

from .dependencies import _resolve_memory_integration, _resolve_unified_memory
from .helpers import memory_t
from .l2.status import (
    build_background_pending_response,
    build_embedding_pending_from_store,
    build_l2_pending_payload,
    default_projection_backlog,
)
from .router import memory_router
from .statistics import build_layer_statistics

PENDING_ASSERTION_STATES = ["tentative", "contradicted"]
MAX_SUPERSEDED_CHAIN_DEPTH = 8


@dataclass(frozen=True)
class _DashboardStores:
    unified_memory: Any
    memory_integration: Any
    l1: Any
    l2: Any
    l3: Any
    l4: Any


@dataclass(frozen=True)
class _DashboardSnapshot:
    l1_count: int
    l2_relation_count: int
    l2_assertion_count: int
    l3_count: int
    l4_count: int
    projection_backlog: dict[str, Any]
    source_counts: list[dict[str, Any]]
    pending_count: int
    pending_items: list[dict[str, Any]]
    l1_today_count: int
    l2_today_assertion_count: int
    l3_today_count: int
    l2_edge_backlog: dict[str, Any]
    pipeline_stats: dict[str, Any]


def _start_of_local_today() -> float:
    now = datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _project_source_count(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(row.get("source") or ""),
        "event_count": int(row.get("event_count") or 0),
        "avg_importance": float(row.get("avg_importance") or 0.0),
        "first_event_at": row.get("min_timestamp"),
        "last_event_at": row.get("max_timestamp"),
    }


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


async def _resolve_superseded_successor(
    l2: Any, assertion: dict[str, Any]
) -> dict[str, Any] | None:
    get_assertion = getattr(l2, "get_tom_assertion", None)
    if not callable(get_assertion):
        return None

    next_id = _clean_text(assertion.get("superseded_by"))
    if not next_id:
        return None

    seen = {_clean_text(assertion.get("assertion_id"))}
    successor: dict[str, Any] | None = None
    for _ in range(MAX_SUPERSEDED_CHAIN_DEPTH):
        if not next_id or next_id in seen:
            break
        seen.add(next_id)
        candidate = await get_assertion(assertion_id=next_id)
        if not candidate:
            break
        successor = dict(candidate)
        next_id = _clean_text(successor.get("superseded_by"))
    return successor


async def _enrich_pending_assertions(l2: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in items:
        assertion = dict(item)
        successor = await _resolve_superseded_successor(l2, assertion)
        if successor is not None:
            current_value = _clean_text(successor.get("trait_value"))
            if current_value:
                assertion["conflict_context"] = {
                    "kind": "superseded_by_assertion",
                    "previous_assertion_id": _clean_text(assertion.get("assertion_id")),
                    "previous_value": _clean_text(assertion.get("trait_value")),
                    "current_assertion_id": _clean_text(successor.get("assertion_id")),
                    "current_value": current_value,
                }
        enriched.append(assertion)
    return enriched


async def _default_projection_backlog() -> dict[str, int]:
    return default_projection_backlog()


async def _zero() -> int:
    return 0


async def _empty_list() -> list[dict[str, Any]]:
    return []


async def _default_l2_edge_backlog() -> dict[str, int]:
    return {"pending": 0}


def _total_processing_pending(backlog: dict[str, Any]) -> int:
    l2 = dict(backlog.get("l2") or {})
    l2_edge_embeddings = dict(backlog.get("l2_edge_embeddings") or {})
    layers = [
        dict(backlog.get("l1_embeddings") or {}),
        dict(backlog.get("l3_embeddings") or {}),
        dict(backlog.get("l4_embeddings") or {}),
    ]
    return max(
        int(l2.get("extract_pending", 0))
        + int(l2.get("reconcile_pending", 0))
        + int(l2.get("snapshot_pending", 0))
        + int(l2_edge_embeddings.get("pending", 0))
        + sum(int(layer.get("pending", 0) or 0) for layer in layers),
        0,
    )


@memory_router.get("/dashboard")
async def get_memory_dashboard(
    pending_limit: int = Query(default=8, ge=1, le=500),
    pending_offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Return the user-facing memory overview dashboard read model."""
    stores = _resolve_dashboard_stores()
    snapshot = await _collect_dashboard_snapshot(stores, pending_limit, pending_offset)
    response = _build_dashboard_response(stores, snapshot, pending_limit)
    response["pending_assertions"]["offset"] = pending_offset
    return response


def _resolve_dashboard_stores() -> _DashboardStores:
    unified_memory = _resolve_unified_memory()
    memory_integration = _resolve_memory_integration()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )
    return _DashboardStores(
        unified_memory=unified_memory,
        memory_integration=memory_integration,
        l1=getattr(unified_memory, "l1", None),
        l2=getattr(unified_memory, "l2", None),
        l3=getattr(unified_memory, "l3", None),
        l4=getattr(unified_memory, "l4", None),
    )


async def _collect_dashboard_snapshot(
    stores: _DashboardStores,
    pending_limit: int,
    pending_offset: int = 0,
) -> _DashboardSnapshot:
    unified_memory = stores.unified_memory
    l1 = stores.l1
    l2 = stores.l2
    l3 = stores.l3
    l4 = stores.l4
    today_start = _start_of_local_today()
    pipeline_stats = (
        unified_memory.get_l2_pipeline_stats()
        if hasattr(unified_memory, "get_l2_pipeline_stats")
        else {}
    )
    (
        l1_count,
        l2_rel_count,
        l2_assertion_count,
        l3_count,
        l4_count,
        projection_backlog,
        source_counts,
        pending_count,
        pending_items,
        l1_today_count,
        l2_today_assertion_count,
        l3_today_count,
        l2_edge_backlog,
    ) = await asyncio.gather(
        l1.count_events() if l1 else _zero(),
        l2.count_relationships() if l2 else _zero(),
        l2.count_tom_assertions() if l2 else _zero(),
        l3.count_summaries() if l3 else _zero(),
        l4.count_skills() if l4 else _zero(),
        _projection_backlog_coro(unified_memory),
        _source_counts_coro(l1),
        _pending_assertion_count_coro(l2),
        _pending_assertion_items_coro(l2, pending_limit, pending_offset),
        l1.count_events(start_time=today_start) if l1 else _zero(),
        _l2_today_assertion_count_coro(l2, today_start),
        l3.count_summaries(start_time=today_start) if l3 else _zero(),
        _l2_edge_backlog_coro(unified_memory),
    )
    if l2:
        pending_items = await _enrich_pending_assertions(l2, pending_items)
    return _DashboardSnapshot(
        l1_count=l1_count,
        l2_relation_count=l2_rel_count,
        l2_assertion_count=l2_assertion_count,
        l3_count=l3_count,
        l4_count=l4_count,
        projection_backlog=projection_backlog,
        source_counts=source_counts,
        pending_count=pending_count,
        pending_items=pending_items,
        l1_today_count=l1_today_count,
        l2_today_assertion_count=l2_today_assertion_count,
        l3_today_count=l3_today_count,
        l2_edge_backlog=l2_edge_backlog,
        pipeline_stats=pipeline_stats,
    )


def _projection_backlog_coro(unified_memory: Any):
    if hasattr(unified_memory, "get_l2_projection_backlog"):
        return unified_memory.get_l2_projection_backlog()
    return _default_projection_backlog()


def _l2_edge_backlog_coro(unified_memory: Any):
    if hasattr(unified_memory, "get_l2_edge_embedding_backlog"):
        return unified_memory.get_l2_edge_embedding_backlog()
    return _default_l2_edge_backlog()


def _source_counts_coro(l1: Any):
    if not l1:
        return _empty_list()
    return l1.summarize_event_sources(
        cognition_eligible=True,
        exclude_retention_class=RetentionClass.DISPOSABLE.label,
    )


def _pending_assertion_count_coro(l2: Any):
    if not l2:
        return _zero()
    return l2.count_tom_assertions(
        validation_states=PENDING_ASSERTION_STATES,
        include_expired=False,
        include_inactive=False,
    )


def _pending_assertion_items_coro(l2: Any, pending_limit: int, offset: int = 0):
    if not l2:
        return _empty_list()
    return l2.list_tom_assertions(
        validation_states=PENDING_ASSERTION_STATES,
        include_expired=False,
        include_inactive=False,
        limit=pending_limit,
        offset=offset,
    )


def _l2_today_assertion_count_coro(l2: Any, today_start: float):
    if not l2:
        return _zero()
    return l2.count_tom_assertions(
        temporal_clause=("first_inferred_at >= ?", [today_start]),
        include_expired=False,
        include_inactive=False,
    )


def _build_dashboard_response(
    stores: _DashboardStores,
    snapshot: _DashboardSnapshot,
    pending_limit: int,
) -> dict[str, Any]:
    statistics = _build_dashboard_statistics(stores, snapshot)
    attention = dict(statistics.get("attention") or {})
    attention["pending_assertions"] = int(snapshot.pending_count)
    statistics["attention"] = attention
    return {
        "statistics": statistics,
        "source_counts": [_project_source_count(row) for row in snapshot.source_counts],
        "attention": attention,
        "processing_backlog": _build_processing_backlog(stores, snapshot),
        "deltas": {"today": _build_today_delta(snapshot)},
        "pending_assertions": {
            "items": snapshot.pending_items,
            "total": int(snapshot.pending_count),
            "limit": int(pending_limit),
            "offset": 0,
        },
    }


def _build_dashboard_statistics(
    stores: _DashboardStores,
    snapshot: _DashboardSnapshot,
) -> dict[str, Any]:
    return build_layer_statistics(
        unified_memory=stores.unified_memory,
        l1_count=snapshot.l1_count,
        l2_relation_count=snapshot.l2_relation_count,
        l2_assertion_count=snapshot.l2_assertion_count,
        l3_count=snapshot.l3_count,
        l4_count=snapshot.l4_count,
        integration_stats=(
            stores.memory_integration.get_statistics() if stores.memory_integration else None
        ),
    )


def _build_processing_backlog(
    stores: _DashboardStores,
    snapshot: _DashboardSnapshot,
) -> dict[str, Any]:
    processing_backlog = build_background_pending_response(
        l2_pending=build_l2_pending_payload(
            pipeline_stats=snapshot.pipeline_stats,
            projection_backlog=snapshot.projection_backlog,
        ),
        l2_edge_pending=snapshot.l2_edge_backlog,
        l1_pending=build_embedding_pending_from_store(stores.l1),
        l3_pending=build_embedding_pending_from_store(stores.l3),
        l4_pending=build_embedding_pending_from_store(stores.l4),
    )
    processing_backlog["total_pending"] = _total_processing_pending(processing_backlog)
    return processing_backlog


def _build_today_delta(snapshot: _DashboardSnapshot) -> dict[str, Any]:
    l1_today_count = int(snapshot.l1_today_count)
    l2_today_assertion_count = int(snapshot.l2_today_assertion_count)
    l3_today_count = int(snapshot.l3_today_count)
    return {
        "stored_records": l1_today_count + l2_today_assertion_count + l3_today_count,
        "l1_events": l1_today_count,
        "l2_assertions": l2_today_assertion_count,
        "l3_summaries": l3_today_count,
        "disk_usage_bytes": None,
    }
