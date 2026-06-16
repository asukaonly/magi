"""L2 episode API routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import HTTPException, Query, status

from ..dependencies import _resolve_unified_memory
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import EpisodeAnnotationRequest, EpisodeMergeRequest


@memory_router.get("/l2/episodes")
async def list_l2_episodes(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    episode_type: Optional[str] = Query(default=None),
    time_start: Optional[float] = Query(default=None),
    time_end: Optional[float] = Query(default=None),
    parent_episode_id: Optional[str] = Query(default=None),
    surface: Optional[str] = Query(default=None, description="'standout' for canonical chapters"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List episodes with optional filters.

    When ``surface='standout'``, only ``magi_standout=1 OR user_pinned=1``
    episodes are returned, and each item carries a ``summary`` field with the
    linked L3 episodic summary (or null if not generated yet).
    """
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    if surface == "standout":
        items = await unified_memory.l2.list_standout_episodes(
            period_start=time_start,
            period_end=time_end,
            limit=limit,
        )
        # Join L3 episodic summary per item.
        if unified_memory.l3 is not None:
            for item in items:
                episode_id = str(item.get("episode_id") or "")
                if not episode_id:
                    item["episode_summary"] = None
                    continue
                l3_row = await unified_memory.l3.get_episodic_summary_by_episode_id(episode_id)
                if l3_row is None:
                    item["episode_summary"] = None
                else:
                    metadata = l3_row.get("insight_metadata") or {}
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except (json.JSONDecodeError, ValueError):
                            metadata = {}
                    if not isinstance(metadata, dict):
                        metadata = {}
                    item["episode_summary"] = {
                        "summary_id": l3_row.get("summary_id"),
                        "content": l3_row.get("content") or "",
                        "label": str(metadata.get("label") or ""),
                        "updated_at": l3_row.get("updated_at"),
                        "is_fallback": bool(metadata.get("fallback")),
                    }
        else:
            for item in items:
                item["episode_summary"] = None
        return {
            "items": items,
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "surface": "standout",
        }

    # Default path: existing behavior unchanged.
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


@memory_router.post("/l2/episodes/{episode_id}/merge")
async def merge_l2_episode(episode_id: str, body: EpisodeMergeRequest):
    """Merge another episode into the target episode."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    if body.absorbed_id == episode_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.same_episode_merge", "Cannot merge an episode into itself"),
        )

    merged = await unified_memory.l2.merge_episodes(
        survivor_id=episode_id,
        absorbed_id=body.absorbed_id,
    )
    if merged is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
        )
    return merged


@memory_router.post("/l2/episodes/reconsolidate")
async def reconsolidate_episodes_endpoint():
    """One-shot: consolidate candidate→active + mark standouts + generate L3 summaries.

    For the governance "立即整理" button. Synchronous: returns when all summary
    generation has finished. Each LLM call has a 30s timeout; in the worst case
    this can take a while if many active episodes still lack a summary.

    Catch-up scope: every ``status='active'`` episode lacking an L3 episodic
    summary gets one generated (widened from the old standout-only filter), so
    pre-existing active episodes that never got a title are backfilled here.
    Eager generation on new promotes is handled by the maintenance scheduler.
    """
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )

    from magi.memory.l2.episode_formation import consolidate_episodes
    stats = await consolidate_episodes(unified_memory.l2)

    summaries_generated = 0
    summary_errors: list[str] = []

    if unified_memory.l3 is not None and unified_memory.l1 is not None:
        # Catch-up: every active episode lacking an L3 episodic summary (newly
        # promoted ones are already 'active', so they are included here).
        active_episodes = await unified_memory.l2.list_episodes(status="active", limit=500)
        episode_ids = [
            str(ep.get("episode_id") or "").strip()
            for ep in active_episodes
            if ep.get("episode_id")
        ]
        result = await unified_memory.l3.generate_missing_episodic_summaries(
            l1_store=unified_memory.l1,
            l2_store=unified_memory.l2,
            episode_ids=episode_ids,
        )
        summaries_generated = int(result.get("generated") or 0)
        summary_errors = list(result.get("errors") or [])

    return {
        "promoted": stats.promoted,
        "standouts": stats.standouts,
        "merged": stats.merged,
        "invalidated": stats.invalidated,
        "summaries_generated": summaries_generated,
        "summary_errors": summary_errors,
    }
