"""L2 status response helpers for the memory API."""
from __future__ import annotations

from typing import Any, Mapping

from ..helpers import build_embedding_pending, build_l2_pending_breakdown


def default_projection_backlog() -> dict[str, int]:
    return {"pending": 0, "claimed": 0, "completed": 0, "failed": 0}


def empty_l2_statistics_response() -> dict[str, Any]:
    return {
        "is_running": False,
        "relation_count": 0,
        "assertion_count": 0,
        "extract_enqueued": 0,
        "extract_active": 0,
        "extract_completed": 0,
        "extract_failed": 0,
        "extract_skipped": 0,
        "reconcile_enqueued": 0,
        "reconcile_active": 0,
        "reconcile_completed": 0,
        "reconcile_failed": 0,
        "snapshot_enqueued": 0,
        "snapshot_active": 0,
        "snapshot_completed": 0,
        "snapshot_failed": 0,
        "relations_written": 0,
        "assertions_written": 0,
        "extract_by_evidence_class": {},
        "skip_by_reason": {},
        "projection_backlog": default_projection_backlog(),
        "db_path": None,
    }


def build_l2_statistics_response(
    *,
    relation_count: int,
    assertion_count: int,
    pipeline_stats: Mapping[str, Any],
    projection_backlog: Mapping[str, Any],
    db_path: str | None,
) -> dict[str, Any]:
    return {
        "is_running": bool(pipeline_stats.get("is_running", False)),
        "relation_count": relation_count,
        "assertion_count": assertion_count,
        "extract_enqueued": int(pipeline_stats.get("extract_enqueued", 0)),
        "extract_active": int(pipeline_stats.get("extract_active", 0)),
        "extract_completed": int(pipeline_stats.get("extract_completed", 0)),
        "extract_failed": int(pipeline_stats.get("extract_failed", 0)),
        "extract_skipped": int(pipeline_stats.get("extract_skipped", 0)),
        "reconcile_enqueued": int(pipeline_stats.get("reconcile_enqueued", 0)),
        "reconcile_active": int(pipeline_stats.get("reconcile_active", 0)),
        "reconcile_completed": int(pipeline_stats.get("reconcile_completed", 0)),
        "reconcile_failed": int(pipeline_stats.get("reconcile_failed", 0)),
        "snapshot_enqueued": int(pipeline_stats.get("snapshot_enqueued", 0)),
        "snapshot_active": int(pipeline_stats.get("snapshot_active", 0)),
        "snapshot_completed": int(pipeline_stats.get("snapshot_completed", 0)),
        "snapshot_failed": int(pipeline_stats.get("snapshot_failed", 0)),
        "relations_written": int(pipeline_stats.get("relations_written", 0)),
        "assertions_written": int(pipeline_stats.get("assertions_written", 0)),
        "extract_by_evidence_class": dict(pipeline_stats.get("extract_by_evidence_class", {})),
        "skip_by_reason": dict(pipeline_stats.get("skip_by_reason", {})),
        "projection_backlog": dict(projection_backlog),
        "db_path": db_path,
    }


def empty_l2_pending_response() -> dict[str, Any]:
    return {"is_running": False, **build_l2_pending_breakdown({}, default_projection_backlog())}


def build_l2_pending_payload(
    *,
    pipeline_stats: Mapping[str, Any],
    projection_backlog: Mapping[str, Any],
) -> dict[str, int]:
    return build_l2_pending_breakdown(dict(pipeline_stats), dict(projection_backlog))


def build_l2_pending_response(
    *,
    pipeline_stats: Mapping[str, Any],
    projection_backlog: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "is_running": bool(pipeline_stats.get("is_running", False)),
        **build_l2_pending_payload(
            pipeline_stats=pipeline_stats,
            projection_backlog=projection_backlog,
        ),
    }


def build_embedding_pending_from_store(store: Any) -> dict[str, Any]:
    if store is None or not hasattr(store, "get_statistics"):
        return build_embedding_pending(None)
    return build_embedding_pending(store.get_statistics())


def empty_background_pending_response() -> dict[str, Any]:
    return build_background_pending_response(
        l2_pending=build_l2_pending_payload(
            pipeline_stats={},
            projection_backlog=default_projection_backlog(),
        ),
        l2_edge_pending={"pending": 0},
        l1_pending=build_embedding_pending(None),
        l3_pending=build_embedding_pending(None),
        l4_pending=build_embedding_pending(None),
    )


def build_background_pending_response(
    *,
    l2_pending: Mapping[str, int],
    l2_edge_pending: Mapping[str, int],
    l1_pending: Mapping[str, Any],
    l3_pending: Mapping[str, Any],
    l4_pending: Mapping[str, Any],
) -> dict[str, Any]:
    all_idle = (
        int(l2_pending["extract_pending"]) == 0
        and int(l2_pending["reconcile_pending"]) == 0
        and int(l2_pending["snapshot_pending"]) == 0
        and int(l2_edge_pending.get("pending", 0)) == 0
        and int(l1_pending["pending"]) == 0
        and int(l3_pending["pending"]) == 0
        and int(l4_pending["pending"]) == 0
    )
    return {
        "l2": dict(l2_pending),
        "l2_edge_embeddings": dict(l2_edge_pending),
        "l1_embeddings": dict(l1_pending),
        "l3_embeddings": dict(l3_pending),
        "l4_embeddings": dict(l4_pending),
        "all_idle": all_idle,
    }
