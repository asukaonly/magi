"""Small helper functions shared by memory API routes."""
from __future__ import annotations

from datetime import date, datetime, time as datetime_time
from typing import Any, Dict

from fastapi import HTTPException, status

from magi import i18n as core_i18n
from magi.identity.defaults import CANONICAL_LOCAL_USER
from magi.memory.event_contracts import MemoryEvent


_CANONICAL_SELF_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"


def memory_t(key: str, fallback: str, **kwargs: Any) -> str:
    return core_i18n.t(key, fallback=fallback, **kwargs)


def _memory_user_entity_id(raw_user_id: Any) -> str:
    raw = str(raw_user_id or "").strip()
    if not raw:
        return _CANONICAL_SELF_ENTITY_ID
    if raw.startswith("user:"):
        return raw
    return f"user:{raw}"


def canonical_self_id(unified_memory: Any) -> str:
    resolver = getattr(unified_memory, "identity_resolver", None)
    if resolver is None:
        return _CANONICAL_SELF_ENTITY_ID
    if hasattr(resolver, "canonical_local"):
        return _memory_user_entity_id(resolver.canonical_local())
    return _memory_user_entity_id(getattr(resolver, "default_memory_owner_id", None))


def build_l2_pending_breakdown(
    pipeline_stats: Dict[str, Any],
    projection_backlog: Dict[str, Any] | None = None,
) -> Dict[str, int]:
    durable_projection = dict(projection_backlog or {})
    extract_active = max(int(pipeline_stats.get("extract_active", 0)), 0)
    reconcile_active = max(int(pipeline_stats.get("reconcile_active", 0)), 0)
    snapshot_active = max(int(pipeline_stats.get("snapshot_active", 0)), 0)
    in_memory_extract_pending = max(
        int(pipeline_stats.get("extract_enqueued", 0))
        - int(pipeline_stats.get("extract_completed", 0))
        - int(pipeline_stats.get("extract_failed", 0))
        - int(pipeline_stats.get("extract_skipped", 0)),
        0,
    )
    durable_projection_pending = max(
        int(durable_projection.get("pending", 0)) + int(durable_projection.get("claimed", 0)),
        0,
    )
    return {
        "extract_pending": max(
            in_memory_extract_pending,
            durable_projection_pending,
            extract_active,
        ),
        "extract_active": extract_active,
        "reconcile_pending": max(
            int(pipeline_stats.get("reconcile_enqueued", 0))
            - int(pipeline_stats.get("reconcile_completed", 0))
            - int(pipeline_stats.get("reconcile_failed", 0)),
            reconcile_active,
            0,
        ),
        "reconcile_active": reconcile_active,
        "snapshot_pending": max(
            int(pipeline_stats.get("snapshot_enqueued", 0))
            - int(pipeline_stats.get("snapshot_completed", 0))
            - int(pipeline_stats.get("snapshot_failed", 0)),
            snapshot_active,
            0,
        ),
        "snapshot_active": snapshot_active,
        "projection_pending": max(int(durable_projection.get("pending", 0)), 0),
        "projection_claimed": max(int(durable_projection.get("claimed", 0)), 0),
        "projection_failed": max(int(durable_projection.get("failed", 0)), 0),
    }


def build_embedding_pending(stats: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(stats or {})
    queued = max(int(payload.get("embedding_queue_size", 0) or 0), 0)
    active = max(int(payload.get("embedding_active_count", 0) or 0), 0)
    return {
        "pending": queued + active,
        "queued": queued,
        "active": active,
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
            detail=memory_t(
                "memory.errors.invalid_date",
                "Invalid date value: {value}",
                value=normalized,
            ),
        ) from exc
    boundary = datetime_time.max if end_of_day else datetime_time.min
    return datetime.combine(parsed, boundary).timestamp()
