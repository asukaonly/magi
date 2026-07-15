"""L2 user-agency and forget API routes."""

from __future__ import annotations

from fastapi import HTTPException, status

from ..dependencies import _resolve_unified_memory
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import ForgetEntityRequest, ForgetEpisodeRequest, ForgetTimeRangeRequest
from .....memory.event_contracts import generate_event_id


@memory_router.patch("/l2/edges/{triple_id}/reject")
async def reject_l2_edge(triple_id: str):
    """User-initiated rejection of a KG edge."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    result = await unified_memory.l2.reject_edge(
        triple_id=triple_id,
        audit_event_id=generate_event_id(prefix="correction_audit"),
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.edge_not_found", "Edge not found"))
    return result


@memory_router.post("/forget/entity")
async def forget_entity(body: ForgetEntityRequest):
    """Cascade forget: invalidate all L2 records derived from an entity."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )

    l2_counts = await unified_memory.l2.forget_entity(entity_id=body.entity_id)

    l1_deleted = 0
    if body.delete_l1_events and unified_memory.l1 is not None:
        entity_events = await unified_memory.l1.get_entity_event_ids([body.entity_id])
        event_ids = entity_events.get(body.entity_id, [])
        for eid in event_ids:
            if await unified_memory.l1.mark_deleted(eid):
                l1_deleted += 1

    return {"l2_counts": l2_counts, "l1_events_deleted": l1_deleted}


@memory_router.post("/forget/time-range")
async def forget_time_range(body: ForgetTimeRangeRequest):
    """Cascade forget: invalidate L2 records inferred during a time range."""
    if body.end <= body.start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.end_must_be_greater_than_start", "end must be greater than start"),
        )

    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )

    l2_counts = await unified_memory.l2.forget_time_range(start=body.start, end=body.end)

    l1_deleted = 0
    if body.delete_l1_events and unified_memory.l1 is not None:
        events = await unified_memory.l1.query_events(start_time=body.start, end_time=body.end, limit=10000)
        for ev in events:
            eid = ev.get("event_id") or ev.get("id")
            if eid and await unified_memory.l1.mark_deleted(str(eid)):
                l1_deleted += 1

    return {"l2_counts": l2_counts, "l1_events_deleted": l1_deleted}


@memory_router.post("/forget/episode")
async def forget_episode(body: ForgetEpisodeRequest):
    """Invalidate a specific episode and optionally its member events."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )

    result = await unified_memory.l2.forget_episode(
        episode_id=body.episode_id,
        delete_events=body.delete_events,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))

    l1_deleted = 0
    if body.delete_events and unified_memory.l1 is not None:
        for eid in result.get("event_ids", []):
            if await unified_memory.l1.mark_deleted(eid):
                l1_deleted += 1

    return {**result, "l1_events_deleted": l1_deleted}
