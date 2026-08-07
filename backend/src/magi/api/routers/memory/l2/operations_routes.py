"""L2 pipeline operation API routes."""

from __future__ import annotations

from fastapi import HTTPException, status

from magi.memory.l2.models import ManualL2EventRequest

from ..dependencies import _resolve_unified_memory
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import L2EntityActionBody, ManualL2EventBody


@memory_router.post("/l2/manual-event")
async def create_manual_l2_event(body: ManualL2EventBody):
    """Inject a manual event into the L1 -> L2 write path."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )
    result = await unified_memory.ingest_manual_l2_event(
        ManualL2EventRequest(
            text=body.text,
            user_id=body.user_id,
            session_id=body.session_id,
            source=body.source,
            entity_focus_hint=body.entity_focus_hint,
        )
    )
    return {"queued": True, **result}


@memory_router.post("/l2/extract/{event_id}")
async def replay_l2_extraction(event_id: str):
    """Replay event extraction for an existing L1 event."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )
    queued = await unified_memory.replay_l2_extraction(event_id)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.event_not_found_or_pipeline_unavailable", "Event not found or pipeline unavailable"),
        )
    return {"queued": True, "event_id": event_id}


@memory_router.post("/l2/reconcile")
async def trigger_l2_reconcile(body: L2EntityActionBody):
    """Manually enqueue entity reconcile work."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )
    queued = await unified_memory.reconcile_entities(body.entity_ids)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.no_valid_entities_to_reconcile", "No valid entities to reconcile"),
        )
    return {"queued": True, "entity_ids": body.entity_ids}


@memory_router.post("/l2/snapshot-refresh")
async def trigger_l2_snapshot_refresh(body: L2EntityActionBody):
    """Manually enqueue snapshot refresh work."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )
    queued = await unified_memory.refresh_l2_snapshots(body.entity_ids)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.no_valid_entities_to_materialize", "No valid entities to materialize"),
        )
    return {"queued": True, "entity_ids": body.entity_ids}


@memory_router.post("/l2/projection-flush")
async def trigger_l2_projection_flush():
    """Immediately claim pending durable L2 projection jobs."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )

    batch_count = await unified_memory.flush_l2_projection_jobs()
    return {"queued": batch_count > 0, "batch_count": batch_count}
