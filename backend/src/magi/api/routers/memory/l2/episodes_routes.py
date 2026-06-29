"""L2 episode API routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, Query, status

from magi.api.services.l2_episode_review_service import (
    L2EpisodeReviewService,
    reconsolidate_episode_reviews,
)

from ..dependencies import _resolve_unified_memory
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import (
    EpisodeAnnotationRequest,
    EpisodeEventIdsRequest,
    EpisodeMergeRequest,
    EpisodeSplitRequest,
)


def _require_l2_memory() -> Any:
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    return unified_memory


def _episode_review_service() -> L2EpisodeReviewService:
    return L2EpisodeReviewService(_require_l2_memory())


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
    """List episodes with optional filters."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    return await L2EpisodeReviewService(unified_memory).list_episodes(
        status_filter=status_filter,
        episode_type=episode_type,
        time_start=time_start,
        time_end=time_end,
        parent_episode_id=parent_episode_id,
        surface=surface,
        limit=limit,
        offset=offset,
    )


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
    return await _episode_review_service().get_episode_review(episode_id)


@memory_router.post("/l2/episodes/{episode_id}/regenerate")
async def regenerate_l2_episode(episode_id: str):
    """Regenerate the L3 recap for an active episode and refresh review fields."""
    return await _episode_review_service().regenerate_episode_review(episode_id)


@memory_router.get("/l2/episodes/{episode_id}/event-candidates")
async def list_l2_episode_event_candidates(
    episode_id: str,
    limit: int = Query(default=20, ge=1, le=50),
):
    """List nearby or similar L1 events that can be added to an episode."""
    return await _episode_review_service().list_event_candidates(
        episode_id=episode_id,
        limit=limit,
    )


@memory_router.post("/l2/episodes/{episode_id}/events")
async def add_l2_episode_events(episode_id: str, body: EpisodeEventIdsRequest):
    """Add candidate L1 events to an episode and refresh its recap."""
    return await _episode_review_service().add_episode_events(
        episode_id=episode_id,
        event_ids=body.event_ids,
    )


@memory_router.delete("/l2/episodes/{episode_id}/events")
async def remove_l2_episode_events(episode_id: str, body: EpisodeEventIdsRequest):
    """Remove L1 events from an episode and refresh its recap."""
    return await _episode_review_service().remove_episode_events(
        episode_id=episode_id,
        event_ids=body.event_ids,
    )


@memory_router.patch("/l2/episodes/{episode_id}")
async def annotate_l2_episode(episode_id: str, body: EpisodeAnnotationRequest):
    """User annotation on an episode."""
    return await _episode_review_service().annotate_episode(
        episode_id=episode_id,
        user_label=body.user_label,
        user_note=body.user_note,
        user_pinned=body.user_pinned,
    )


@memory_router.get("/l2/episodes/{episode_id}/merge-candidates")
async def list_l2_episode_merge_candidates(
    episode_id: str,
    limit: int = Query(default=10, ge=1, le=50),
):
    """List nearby or similar active episodes that can be merged."""
    return await _episode_review_service().list_merge_candidates(
        episode_id=episode_id,
        limit=limit,
    )


@memory_router.post("/l2/episodes/{episode_id}/merge")
async def merge_l2_episode(episode_id: str, body: EpisodeMergeRequest):
    """Merge another episode into the target episode."""
    return await _episode_review_service().merge_episode(
        episode_id=episode_id,
        absorbed_id=body.absorbed_id,
    )


@memory_router.post("/l2/episodes/{episode_id}/split-preview")
async def preview_l2_episode_split(episode_id: str, body: EpisodeSplitRequest):
    """Preview a chronological split without mutating episode storage."""
    return await _episode_review_service().preview_episode_split(
        episode_id=episode_id,
        break_after_event_id=body.break_after_event_id,
    )


@memory_router.post("/l2/episodes/{episode_id}/split")
async def split_l2_episode(episode_id: str, body: EpisodeSplitRequest):
    """Split an episode into two chronological child episodes."""
    return await _episode_review_service().split_episode(
        episode_id=episode_id,
        break_after_event_id=body.break_after_event_id,
    )


@memory_router.post("/l2/episodes/reconsolidate")
async def reconsolidate_episodes_endpoint():
    """Consolidate episode candidates, mark standouts, and fill review summaries."""
    return await reconsolidate_episode_reviews(_require_l2_memory())
