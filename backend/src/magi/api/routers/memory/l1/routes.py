"""L1 event API routes."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import HTTPException, Query, status

from ..dependencies import _resolve_unified_memory
from ..helpers import memory_t
from ..forget_workflow import delete_user_event
from ..router import memory_router
from .events import build_l1_event_query_args, build_l1_events_response


@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    event_id: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    source_item_id: Optional[str] = Query(default=None),
    idempotency_key: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l1:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    query_args = build_l1_event_query_args(
        event_id=event_id,
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        query=query,
        source=source,
        source_item_id=source_item_id,
        idempotency_key=idempotency_key,
        start_date=start_date,
        end_date=end_date,
    )

    events, total = await asyncio.gather(
        unified_memory.l1.query_events(
            **query_args,
            limit=limit,
            offset=offset,
            include_metadata_json=True,
            include_embedding_fields=True,
        ),
        unified_memory.l1.count_events(
            **query_args,
        ),
    )
    return build_l1_events_response(
        events=events,
        total=total,
        limit=limit,
        offset=offset,
    )


@memory_router.delete("/l1/events/{event_id}")
async def delete_l1_event(event_id: str):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.memory_stores_uninitialized",
                "Memory stores not initialized",
            ),
        )

    # Use the raw row so an old manual-entry projection cannot bypass the
    # source-owned deletion workflow merely because it was already hidden.
    # The same raw identity also keeps retry responses stable after L1 has
    # been soft-deleted by the first request.
    event = await unified_memory.l1.get_event(event_id)
    if event is not None and str(event.get("source") or "").strip() == "manual_entry":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=memory_t(
                "memory.errors.manual_entry_requires_source_delete",
                "Delete this item from Manual Memory so it remains editable and consistent",
            ),
        )

    deleted = await delete_user_event(unified_memory, event_id=event_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.event_not_found", "Event not found"),
        )
    return {
        "event_id": event_id,
        "deleted": True,
        "deletion_scope": (
            "projected_memory_only"
            if event is not None and str(event.get("source") or "").strip() == "chat"
            else "source_event"
        ),
    }
