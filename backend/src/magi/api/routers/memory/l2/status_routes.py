"""L2 and background backlog/status API routes."""

from __future__ import annotations

import asyncio

from ..dependencies import _resolve_unified_memory
from ..router import memory_router
from .status import (
    build_background_pending_response,
    build_embedding_pending_from_store,
    build_l2_pending_payload,
    build_l2_pending_response,
    build_l2_statistics_response,
    default_projection_backlog,
    empty_background_pending_response,
    empty_l2_pending_response,
    empty_l2_statistics_response,
)


@memory_router.get("/l2/statistics")
async def get_l2_statistics():
    """Get L2 cognition statistics."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return empty_l2_statistics_response()

    rel_count, tom_count = await asyncio.gather(
        unified_memory.l2.count_relationships(),
        unified_memory.l2.count_tom_assertions(),
    )
    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else default_projection_backlog()
    )
    return build_l2_statistics_response(
        relation_count=rel_count,
        assertion_count=tom_count,
        pipeline_stats=pipeline_stats,
        projection_backlog=projection_backlog,
        db_path=unified_memory.l2.db_path,
    )


@memory_router.get("/l2/pending")
async def get_l2_pending():
    """Get calculated L2 queue backlog for quick polling."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return empty_l2_pending_response()

    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else default_projection_backlog()
    )
    return build_l2_pending_response(
        pipeline_stats=pipeline_stats,
        projection_backlog=projection_backlog,
    )


@memory_router.get("/background/pending")
async def get_background_pending():
    """Get lightweight backlog stats for background memory workers."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        return empty_background_pending_response()

    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else default_projection_backlog()
    )
    return build_background_pending_response(
        l2_pending=build_l2_pending_payload(
            pipeline_stats=pipeline_stats,
            projection_backlog=projection_backlog,
        ),
        l1_pending=build_embedding_pending_from_store(getattr(unified_memory, "l1", None)),
        l3_pending=build_embedding_pending_from_store(getattr(unified_memory, "l3", None)),
        l4_pending=build_embedding_pending_from_store(getattr(unified_memory, "l4", None)),
    )
