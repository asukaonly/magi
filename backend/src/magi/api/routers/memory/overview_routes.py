"""Memory overview, statistics, and clear API routes."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, status

from .clear import build_clear_memory_response
from .dependencies import _resolve_memory_integration, _resolve_unified_memory, get_chat_read_service, logger
from .helpers import memory_t
from .router import memory_router
from .statistics import build_layer_statistics


@memory_router.get("/statistics")
async def get_memory_statistics():
    """Return per-layer memory statistics in L0-L4 format."""
    unified_memory = _resolve_unified_memory()
    memory_integration = _resolve_memory_integration()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )

    async def _zero() -> int:
        return 0

    l1_coro = unified_memory.l1.count_events() if unified_memory.l1 else _zero()
    l2_rel_coro = unified_memory.l2.count_relationships() if unified_memory.l2 else _zero()
    l2_tom_coro = unified_memory.l2.count_tom_assertions() if unified_memory.l2 else _zero()
    l3_coro = unified_memory.l3.count_summaries() if unified_memory.l3 else _zero()
    l4_coro = unified_memory.l4.count_skills() if unified_memory.l4 else _zero()

    l1_count, l2_rel_count, l2_tom_count, l3_count, l4_count = await asyncio.gather(
        l1_coro,
        l2_rel_coro,
        l2_tom_coro,
        l3_coro,
        l4_coro,
    )
    return build_layer_statistics(
        unified_memory=unified_memory,
        l1_count=l1_count,
        l2_relation_count=l2_rel_count,
        l2_assertion_count=l2_tom_count,
        l3_count=l3_count,
        l4_count=l4_count,
        integration_stats=memory_integration.get_statistics() if memory_integration else None,
    )


@memory_router.delete("/clear")
async def clear_memory_layers():
    """Clear all memory layers and chat session mappings."""
    logger.info("clear_memory: request received")
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        logger.warning("clear_memory: memory system not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )

    logger.info("clear_memory: stopping correction work and clearing l2")
    l2_count = await unified_memory.l2.clear() if getattr(unified_memory, "l2", None) else 0
    if getattr(unified_memory, "l2_entity_catalog", None):
        l2_count += await unified_memory.l2_entity_catalog.clear()
    logger.info("clear_memory: l2 done, removed=%d; clearing l0", l2_count)
    l0_count = await unified_memory.l0.clear() if getattr(unified_memory, "l0", None) else 0
    logger.info("clear_memory: l0 done, removed=%d; clearing l1", l0_count)
    l1_count = await unified_memory.l1.clear() if getattr(unified_memory, "l1", None) else 0
    logger.info("clear_memory: l1 done, removed=%d; clearing l3", l1_count)
    l3_count = await unified_memory.l3.clear() if getattr(unified_memory, "l3", None) else 0
    logger.info("clear_memory: l3 done, removed=%d; clearing l4", l3_count)
    l4_count = await unified_memory.l4.clear() if getattr(unified_memory, "l4", None) else 0
    logger.info("clear_memory: l4 done, removed=%d; clearing chat context", l4_count)
    chat_context_count = get_chat_read_service().clear_all_sessions()
    logger.info(
        "clear_memory: complete. l0=%d l1=%d l2=%d l3=%d l4=%d chat=%d",
        l0_count,
        l1_count,
        l2_count,
        l3_count,
        l4_count,
        chat_context_count,
    )

    return build_clear_memory_response(
        l0_count=l0_count,
        l1_count=l1_count,
        l2_count=l2_count,
        l3_count=l3_count,
        l4_count=l4_count,
        chat_context_count=chat_context_count,
    )
