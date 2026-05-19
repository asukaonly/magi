"""Timeline query API router."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from ... import i18n as core_i18n
from ...memory.provider import get_unified_memory
from ...timeline.service import TimelineService

timeline_router = APIRouter()


def get_timeline_service() -> TimelineService:
    try:
        unified_memory = get_unified_memory()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t(
                "timeline.errors.service_unavailable", fallback="Timeline service unavailable"
            ),
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


@timeline_router.get("/standout")
async def get_standout_endpoint(
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(default=50, ge=1, le=200),
):
    from datetime import datetime, timezone

    period_start = period_end = None
    if month:
        try:
            year, mo = (int(p) for p in month.split("-", 1))
            start_dt = datetime(year, mo, 1, tzinfo=timezone.utc)
            end_dt = (
                datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                if mo == 12
                else datetime(year, mo + 1, 1, tzinfo=timezone.utc)
            )
            period_start = start_dt.timestamp()
            period_end = end_dt.timestamp()
        except (ValueError, OverflowError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid month: {month}",
            ) from exc

    service = get_timeline_service()
    items = await service.list_standout(
        period_start=period_start, period_end=period_end, limit=limit,
    )
    return {"month": month, "items": items}


@timeline_router.get("/mood-calendar")
async def get_mood_calendar_endpoint(
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
):
    service = get_timeline_service()
    return await service.list_mood_calendar(month=month)


@timeline_router.get("/context/{anchor_id}")
async def get_timeline_context_bundle(anchor_id: str):
    service = get_timeline_service()
    bundle = await service.get_context_bundle(anchor_id)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "timeline.errors.context_not_found", fallback="Timeline context not found"
            ),
        )
    return bundle
