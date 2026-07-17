"""L2 user-agency and forget API routes."""

from __future__ import annotations

from fastapi import HTTPException, status

from ..dependencies import _resolve_unified_memory
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import ForgetEntityRequest, ForgetEpisodeRequest, ForgetTimeRangeRequest


@memory_router.post("/forget/entity")
async def forget_entity(body: ForgetEntityRequest):
    """Cascade forget: invalidate all L2 records derived from an entity."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    if body.delete_l1_events and unified_memory.l1 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l1_store_uninitialized", "L1 store not initialized"),
        )

    return await unified_memory.forget_entity_memory(
        entity_id=body.entity_id,
        delete_l1_events=body.delete_l1_events,
    )


@memory_router.post("/forget/time-range")
async def forget_time_range(body: ForgetTimeRangeRequest):
    """Cascade forget: invalidate L2 records inferred during a time range."""
    if body.end <= body.start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t(
                "memory.errors.end_must_be_greater_than_start", "end must be greater than start"
            ),
        )

    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    if body.delete_l1_events and unified_memory.l1 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l1_store_uninitialized", "L1 store not initialized"),
        )

    return await unified_memory.forget_time_range_memory(
        start=body.start,
        end=body.end,
        delete_l1_events=body.delete_l1_events,
    )


@memory_router.post("/forget/episode")
async def forget_episode(body: ForgetEpisodeRequest):
    """Invalidate a specific episode and optionally its member events."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    if body.delete_events and unified_memory.l1 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l1_store_uninitialized", "L1 store not initialized"),
        )

    result = await unified_memory.forget_episode_memory(
        episode_id=body.episode_id,
        delete_events=body.delete_events,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
        )

    return result
