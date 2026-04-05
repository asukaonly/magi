"""Timeline query API router."""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from ...core.runtime_bindings import require_unified_memory
from ...timeline.service import TimelineService

timeline_router = APIRouter()


def get_timeline_service() -> TimelineService:
    try:
        unified_memory = require_unified_memory()
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
    focus: str = Query(default="self", pattern="^self$"),
):
    service = get_timeline_service()
    return await service.get_viewport(
        scale=scale,
        start=start,
        end=end,
        query=query,
        timezone=timezone,
        focus=focus,
    )


@timeline_router.get("/context/{anchor_id}")
async def get_timeline_context_bundle(anchor_id: str):
    service = get_timeline_service()
    bundle = await service.get_context_bundle(anchor_id)
    if bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline context not found")
    return bundle


@timeline_router.get("/digests")
async def list_digests(
    limit: int = Query(default=10, ge=1, le=100),
    category: str = Query(default="day", pattern="^(hour|day|week|month)$"),
):
    """List recent L3 temporal digests."""
    try:
        unified_memory = require_unified_memory()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Digest service unavailable",
        ) from exc

    l3 = getattr(unified_memory, "l3", None)
    if l3 is None:
        return []

    summaries = await l3.list_summaries(limit=limit * 3)
    digests = [
        s for s in summaries
        if s.get("summary_type") == "temporal"
        and s.get("summary_category") == category
    ][:limit]
    return digests


@timeline_router.post("/digests/generate")
async def trigger_digest_generation(
    category: str = Query(default="day", pattern="^(hour|day|week|month)$"),
):
    """Manually trigger a digest generation for the most recent period."""
    try:
        unified_memory = require_unified_memory()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Digest service unavailable",
        ) from exc

    l1 = getattr(unified_memory, "l1", None)
    l3 = getattr(unified_memory, "l3", None)
    if l1 is None or l3 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="L1/L3 stores unavailable",
        )

    from ...memory.l3.digest_schedule import _build_persona_context

    now = time.time()
    period_map = {"hour": 3600, "day": 86400, "week": 604800, "month": 2592000}
    period_seconds = period_map.get(category, 86400)

    persona_context = _build_persona_context()
    summary = await l3.generate_temporal_summary(
        l1_store=l1,
        summary_category=category,
        period_start=now - period_seconds,
        period_end=now,
        persona_context=persona_context,
    )
    if summary is None:
        return {"status": "no_events", "summary": None}
    return {"status": "generated", "summary": summary}

