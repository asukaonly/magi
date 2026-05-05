"""L2 episode API routes."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import HTTPException, Query, status

from ..dependencies import _resolve_unified_memory
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import EpisodeAnnotationRequest


@memory_router.get("/l2/episodes")
async def list_l2_episodes(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    episode_type: Optional[str] = Query(default=None),
    time_start: Optional[float] = Query(default=None),
    time_end: Optional[float] = Query(default=None),
    parent_episode_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List episodes with optional filters."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2.list_episodes(
            status=status_filter,
            episode_type=episode_type,
            time_start=time_start,
            time_end=time_end,
            parent_episode_id=parent_episode_id,
            limit=limit,
            offset=offset,
        ),
        unified_memory.l2.count_episodes(status=status_filter),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.get("/l2/episodes/search")
async def search_l2_episodes(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Full-text search over episodes."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": []}
    items = await unified_memory.l2.search_episodes_fts(query=q, limit=limit)
    return {"items": items}


@memory_router.get("/l2/episodes/{episode_id}")
async def get_l2_episode(episode_id: str):
    """Get a single episode with its event memberships."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))
    events = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    return {**episode, "events": events}


@memory_router.patch("/l2/episodes/{episode_id}")
async def annotate_l2_episode(episode_id: str, body: EpisodeAnnotationRequest):
    """User annotation on an episode (label, note, pin)."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    updates: Dict[str, Any] = {}
    if body.user_label is not None:
        updates["user_label"] = body.user_label
    if body.user_note is not None:
        updates["user_note"] = body.user_note
    if body.user_pinned is not None:
        updates["user_pinned"] = 1 if body.user_pinned else 0
        if body.user_pinned:
            updates["status"] = "user_pinned"
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=memory_t("memory.errors.no_fields_to_update", "No fields to update"))
    ok = await unified_memory.l2.update_episode(episode_id=episode_id, **updates)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))
    return await unified_memory.l2.get_episode(episode_id=episode_id)
