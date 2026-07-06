"""L3 reflection API routes."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import Query

from ..dependencies import _resolve_unified_memory
from ..router import memory_router


@memory_router.get("/l3/summaries")
async def list_l3_summaries(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    query: str | None = Query(default=None),
    summary_type: Optional[str] = Query(default=None, description="Filter by type: temporal, thematic, insight"),
    summary_category: Optional[str] = Query(default=None, description="Filter by category: topic, task_reflection, state_change, trend_shift, etc."),
):
    """List L3 reflection summaries."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l3:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    items, total = await asyncio.gather(
        unified_memory.l3.list_summaries(limit=limit, offset=offset, query=query),
        unified_memory.l3.count_summaries(query=query),
    )
    if summary_type:
        items = [s for s in items if s.get("summary_type") == summary_type]
    if summary_category:
        items = [s for s in items if s.get("summary_category") == summary_category]
    return {"items": items, "total": total, "limit": limit, "offset": offset}
