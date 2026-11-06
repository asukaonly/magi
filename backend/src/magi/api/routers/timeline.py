"""Timeline query API router."""

from __future__ import annotations

from typing import Literal, Optional
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from ... import i18n as core_i18n
from ..runtime_dependencies import get_api_runtime_dependencies
from ...timeline.cover_preferences import TimelineCoverAssetSource
from ...timeline.service import TimelineService
from ...timeline.period_review import calendar_boundaries

timeline_router = APIRouter()


class TimelineEventContextRequest(BaseModel):
    event_ids: list[str] = Field(min_length=1, max_length=5000)


@timeline_router.post("/context")
async def get_timeline_event_context(payload: TimelineEventContextRequest):
    return await get_timeline_service().get_event_context_bundle(payload.event_ids)


class TimelineCoverPreferenceRequest(BaseModel):
    scale: Literal["month", "week", "day", "hour"]
    start: float
    end: float
    mode: Literal["auto", "asset", "hidden"]
    asset_ref: Optional[str] = None
    source: TimelineCoverAssetSource = "current_period"
    locale: str = "en"


def get_timeline_service() -> TimelineService:
    service = get_api_runtime_dependencies().timeline_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t("timeline.errors.service_unavailable", fallback="Timeline service unavailable"),
        )
    return service


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
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise HTTPException(status_code=422, detail="Timeline window must be finite and increasing")
    if scale in ('week', 'month') and end - start > 32 * 86400:
        raise HTTPException(status_code=422, detail="Period reviews support at most 32 days")
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid timeline timezone") from exc
    if scale in ('week', 'month'):
        try:
            boundaries = calendar_boundaries(start, end, timezone)
            if scale == 'week' and len(boundaries) > 8:
                raise ValueError("Week reviews support at most seven calendar days")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@timeline_router.post("/cover")
async def set_timeline_cover_preference(payload: TimelineCoverPreferenceRequest):
    service = get_timeline_service()
    try:
        return await service.set_cover_preference(
            scale=payload.scale,
            start=payload.start,
            end=payload.end,
            mode=payload.mode,
            asset_ref=payload.asset_ref,
            source=payload.source,
            locale=payload.locale,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@timeline_router.get("/standout")
async def get_standout_endpoint(
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    period_start: Optional[float] = Query(default=None),
    period_end: Optional[float] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    from datetime import datetime, timezone

    ps: Optional[float] = period_start
    pe: Optional[float] = period_end
    if ps is None and pe is None and month:
        try:
            year, mo = (int(p) for p in month.split("-", 1))
            start_dt = datetime(year, mo, 1, tzinfo=timezone.utc)
            end_dt = (
                datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                if mo == 12
                else datetime(year, mo + 1, 1, tzinfo=timezone.utc)
            )
            ps = start_dt.timestamp()
            pe = end_dt.timestamp()
        except (ValueError, OverflowError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid month: {month}",
            ) from exc

    service = get_timeline_service()
    items = await service.list_standout(
        period_start=ps,
        period_end=pe,
        limit=limit,
    )
    return {"month": month, "items": items}


@timeline_router.get("/mood-calendar")
async def get_mood_calendar_endpoint(
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
):
    service = get_timeline_service()
    return await service.list_mood_calendar(month=month)


@timeline_router.get("/asset/{asset_ref:path}")
async def get_timeline_asset(asset_ref: str):
    """Serve a timeline asset (e.g. a photo from photo-library://...) as binary."""
    service = get_timeline_service()
    result = await service.serve_asset(asset_ref=asset_ref)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t("timeline.errors.asset_not_found", fallback="Asset not found"),
        )
    body, content_type = result
    return Response(content=body, media_type=content_type)


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
