"""Timeline API router."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...config import get_config
from ...timeline.retention import RetentionService
from ...timeline.service import TimelineService
from ...utils.runtime import get_runtime_paths
from ..routers.memory import get_unified_memory

timeline_router = APIRouter()


class TimelineManualEntryRequest(BaseModel):
    title: str
    summary: str
    text: str
    image_refs: list[str] = Field(default_factory=list)


def get_timeline_service() -> TimelineService:
    unified_memory = get_unified_memory()
    if unified_memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Timeline service unavailable",
        )
    return TimelineService(unified_memory)


def get_retention_service() -> RetentionService:
    return RetentionService()


@timeline_router.get("/events")
async def list_timeline_events(
    limit: int = Query(default=50, ge=1, le=200),
    source_type: Optional[str] = Query(default=None),
):
    service = get_timeline_service()
    retention = get_retention_service()
    events = await service.list_events(limit=limit, source_type=source_type)
    return {
        "events": [
            {
                **event,
                "retention": retention.describe_event(event),
            }
            for event in events
        ],
        "count": len(events),
    }


@timeline_router.get("/events/{event_id}")
async def get_timeline_event(event_id: str):
    service = get_timeline_service()
    retention = get_retention_service()
    detail_loader = getattr(service, "get_event_detail", None)
    event = await detail_loader(event_id) if callable(detail_loader) else await service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline event not found")
    return {
        **event,
        "retention": retention.describe_event(event),
    }


@timeline_router.post("/manual", status_code=status.HTTP_201_CREATED)
async def create_manual_entry(request: TimelineManualEntryRequest):
    service = get_timeline_service()
    event = await service.create_manual_journal(
        title=request.title,
        summary=request.summary,
        text=request.text,
        image_refs=request.image_refs,
    )
    return event.to_dict()


@timeline_router.get("/sources/status")
async def get_timeline_source_status():
    config = get_config()
    runtime_paths = get_runtime_paths()
    sources = config.timeline.sources.model_dump()
    return {
        "sources": [
            {
                "source_name": source_name,
                **source_config,
                "last_error": None,
                "last_success": None,
                "runtime_base_dir": str(runtime_paths.base_dir),
            }
            for source_name, source_config in sources.items()
        ]
    }


@timeline_router.post("/sources/{source_name}/sync")
async def trigger_timeline_source_sync(source_name: str):
    config = get_config()
    sources = config.timeline.sources.model_dump()
    if source_name not in sources:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline source not found")
    return {"queued": True, "source_name": source_name}


@timeline_router.post("/events/{event_id}/reanalyze")
async def reanalyze_timeline_event(event_id: str):
    service = get_timeline_service()
    event = await service.reanalyze_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline event not found")
    return {"queued": True, "event_id": event_id, "event": event}
