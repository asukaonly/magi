"""Memory retrieval API routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import HTTPException, status

from magi.memory.hybrid_retrieval import build_query
from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID

from .dependencies import _resolve_hybrid_retrieval_service
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
    return asdict(payload)
