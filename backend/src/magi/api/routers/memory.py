"""Memory API for the rewritten L0-L4 memory system."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...core.logger import get_logger
from ...memory.hybrid_retrieval import HybridRetrievalService, build_query

logger = get_logger(__name__)

memory_router = APIRouter()


class RetrievalRequest(BaseModel):
    query: str = Field(..., description="Search text")
    query_mode: str = Field(default="detail", description="detail|summary|experience|graph|strategy")
    time_range: Dict[str, Any] = Field(default_factory=dict)
    source_filters: List[str] = Field(default_factory=list)
    domain_filters: List[str] = Field(default_factory=list)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=200)


class ProcedureResponse(BaseModel):
    skill_id: str
    skill_name: str
    skill_category: str
    success_rate: float
    total_attempts: int
    circuit_breaker_state: str


def get_unified_memory():
    try:
        from ...agent import get_unified_memory

        return get_unified_memory()
    except RuntimeError:
        return None


def get_memory_integration():
    try:
        from ...agent import get_memory_integration

        return get_memory_integration()
    except RuntimeError:
        return None


@memory_router.get("/statistics")
async def get_memory_statistics():
    unified_memory = get_unified_memory()
    memory_integration = get_memory_integration()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    stats = await unified_memory.get_statistics()
    if memory_integration:
        stats["integration"] = memory_integration.get_statistics()
    return stats


@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = Query(default=50, ge=1, le=500),
    event_type: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
):
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l1:
        return {"events": [], "stats": {"total": 0}}

    events = await unified_memory.l1.query_events(
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        limit=limit,
    )
    total = await unified_memory.l1.count_events()
    return {"events": events, "stats": {"total": total}}


@memory_router.post("/search")
async def search_memory(request: RetrievalRequest):
    unified_memory = get_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    service = HybridRetrievalService(unified_memory)
    payload = await service.query(
        build_query(
            query=request.query,
            user_id=request.user_id,
            session_id=request.session_id,
            time_range=request.time_range,
            query_mode=request.query_mode,
            source_filters=request.source_filters,
            domain_filters=request.domain_filters,
            limit=request.limit,
        )
    )
    return asdict(payload)


@memory_router.get("/procedures", response_model=List[ProcedureResponse])
async def list_procedures(limit: int = Query(default=100, ge=1, le=500)):
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l4:
        return []

    procedures = await unified_memory.l4.get_all_skills(limit=limit)
    return [
        ProcedureResponse(
            skill_id=str(item["skill_id"]),
            skill_name=str(item["skill_name"]),
            skill_category=str(item["skill_category"]),
            success_rate=float(item["success_rate"]),
            total_attempts=int(item["total_attempts"]),
            circuit_breaker_state=str(item["circuit_breaker_state"]),
        )
        for item in procedures
    ]


@memory_router.get("/tom/{entity_id}")
async def get_tom_snapshot(entity_id: str, entity_type: str = Query(default="user")):
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognition store unavailable",
        )

    snapshot = await unified_memory.l2.get_tom_snapshot(entity_id=entity_id, entity_type=entity_type)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return snapshot
