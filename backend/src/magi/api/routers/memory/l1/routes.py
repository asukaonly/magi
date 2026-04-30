"""L1 event API routes."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import Query

from ..dependencies import _resolve_unified_memory
from ..router import memory_router
from .events import build_l1_event_query_args, build_l1_events_response


@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
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
            include_metadata_json=False,
            include_embedding_fields=False,
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
