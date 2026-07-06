"""L4 procedural memory API routes."""

from __future__ import annotations

import asyncio

from fastapi import Query

from ..dependencies import _resolve_unified_memory
from ..router import memory_router
from .procedures import build_procedure_list_response


@memory_router.get("/procedures")
async def list_procedures(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    query: str | None = Query(default=None),
):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l4:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    items, total = await asyncio.gather(
        unified_memory.l4.get_all_skills(limit=limit, offset=offset, query=query),
        unified_memory.l4.count_skills(query=query),
    )
    return build_procedure_list_response(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
