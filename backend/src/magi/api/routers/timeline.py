"""Timeline query API router."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from ...memory.provider import get_unified_memory
from ...timeline.service import TimelineService

timeline_router = APIRouter()


def get_timeline_service() -> TimelineService:
    try:
        unified_memory = get_unified_memory()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Timeline service unavailable",
        ) from exc
    return TimelineService(unified_memory)


@timeline_router.get("/viewport")
async def get_timeline_viewport(
    scale: str = Query(pattern="^(month|week|day|hour)$"),
    start: float = Query(...),
    end: float = Query(...),
    query: Optional[str] = Query(default=None),
    timezone: Optional[str] = Query(default=None),
    locale: str = Query(default="en"),
    focus: str = Query(default="self", pattern="^self$"),
):
    service = get_timeline_service()
    return await service.get_viewport(
        scale=scale,
        start=start,
        end=end,
        query=query,
        timezone=timezone,
        locale=locale,
        focus=focus,
    )


@timeline_router.get("/context/{anchor_id}")
async def get_timeline_context_bundle(anchor_id: str):
    service = get_timeline_service()
    bundle = await service.get_context_bundle(anchor_id)
    if bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline context not found")
    return bundle

