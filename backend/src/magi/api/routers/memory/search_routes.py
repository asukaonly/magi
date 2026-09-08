"""Memory retrieval API routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import HTTPException, status

from magi.memory.hybrid_retrieval import build_query
from magi.memory.l2.assertion_display import decorate_assertion_display
from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID

from .dependencies import _resolve_hybrid_retrieval_service, _resolve_unified_memory
from .helpers import memory_t
from .router import memory_router
from .schemas import RetrievalRequest


@memory_router.post("/search")
async def search_memory(request: RetrievalRequest):
    retrieval_service = _resolve_hybrid_retrieval_service()
    if retrieval_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.hybrid_retrieval_uninitialized",
                "Hybrid retrieval service not initialized",
            ),
        )

    payload = await retrieval_service.query(
        build_query(
            query=request.query,
            user_id=request.user_id or DEFAULT_USER_ID,
            session_id=request.session_id,
            time_range=request.time_range,
            query_mode=request.query_mode,
            source_filters=request.source_filters,
            domain_filters=request.domain_filters,
            limit=request.limit,
        )
    )
    response = asdict(payload)
    memory = _resolve_unified_memory()
    l2 = getattr(memory, "l2", None)
    locations = [
        (group, index)
        for group, items in response.items() if isinstance(items, list)
        for index, item in enumerate(items)
        if isinstance(item, dict) and (group == "l2_assertions" or "assertion_id" in item)
    ]
    facts = await decorate_assertion_display(
        getattr(l2, "db_path", None), [response[group][index] for group, index in locations]
    )
    for (group, index), fact in zip(locations, facts):
        response[group][index] = fact
    return response
