"""Small helper functions shared by memory API routes."""
from __future__ import annotations

from datetime import date, datetime, time as datetime_time
from typing import Any, Dict

from fastapi import HTTPException, status

from ...memory.event_contracts import MemoryEvent


def canonical_self_id(unified_memory: Any) -> str:
    resolver = getattr(unified_memory, "identity_resolver", None)
    if resolver is None:
        return "user:self"
    return str(getattr(resolver, "default_memory_owner_id", "user:self"))


def build_l2_pending_breakdown(
    pipeline_stats: Dict[str, Any],
    projection_backlog: Dict[str, Any] | None = None,
) -> Dict[str, int]:
    durable_projection = dict(projection_backlog or {})
    return {
        "extract_pending": max(int(durable_projection.get("pending", 0)) + int(durable_projection.get("claimed", 0)), 0),
        "reconcile_pending": max(
            int(pipeline_stats.get("reconcile_enqueued", 0))
            - int(pipeline_stats.get("reconcile_completed", 0))
            - int(pipeline_stats.get("reconcile_failed", 0)),
            0,
        ),
        "snapshot_pending": max(
            int(pipeline_stats.get("snapshot_enqueued", 0))
            - int(pipeline_stats.get("snapshot_completed", 0))
            - int(pipeline_stats.get("snapshot_failed", 0)),
            0,
        ),
        "projection_pending": max(int(durable_projection.get("pending", 0)), 0),
        "projection_claimed": max(int(durable_projection.get("claimed", 0)), 0),
        "projection_failed": max(int(durable_projection.get("failed", 0)), 0),
    }


def build_embedding_pending(stats: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(stats or {})
    pending = int(payload.get("embedding_queue_size", 0) or 0)
    return {
        "pending": max(pending, 0),
        "worker_running": bool(payload.get("embedding_worker_running", False)),
        "vector_enabled": bool(payload.get("vector_enabled", False)),
        "async_embeddings": bool(payload.get("async_embeddings", False)),
    }


def serialize_memory_event(event: MemoryEvent | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(event, MemoryEvent):
        return event.to_dict()
    return dict(event)


def serialize_l1_event_list_item(event: MemoryEvent | Dict[str, Any]) -> Dict[str, Any]:
    payload = serialize_memory_event(event)
    payload.pop("metadata_json", None)
    payload.pop("embedding_status", None)
    payload.pop("embedding_profile_id", None)
    return payload


def parse_day_boundary(value: str | None, *, end_of_day: bool) -> float | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date value: {normalized}",
        ) from exc
    boundary = datetime_time.max if end_of_day else datetime_time.min
    return datetime.combine(parsed, boundary).timestamp()