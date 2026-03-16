"""Memory API for the rewritten L0-L4 memory system."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...core.logger import get_logger
from ...core.runtime_bindings import require_memory_integration, require_unified_memory
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


def _resolve_unified_memory():
    try:
        return require_unified_memory()
    except RuntimeError:
        return None


def _resolve_memory_integration():
    try:
        return require_memory_integration()
    except RuntimeError:
        return None


# =============================================================================
# L0 Working Memory Endpoints
# =============================================================================

@memory_router.get("/l0/sessions")
async def list_l0_sessions():
    """List all active L0 sessions with stats."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l0:
        return {"sessions": [], "stats": {"active_sessions": 0, "total_goals": 0, "total_entities": 0, "total_tactics": 0}}

    sessions = []
    total_goals = 0
    total_entities = 0
    total_tactics = 0

    for session_id, session in unified_memory.l0._sessions.items():
        goals = unified_memory.l0._goal_stack.get(session_id, [])
        entities = unified_memory.l0._active_entities.get(session_id, {})
        tactics = unified_memory.l0._temporary_tactics.get(session_id, {})
        total_goals += len(goals)
        total_entities += len(entities)
        total_tactics += len(tactics)

        sessions.append({
            "session_id": session_id,
            "user_id": session.get("user_id"),
            "status": session.get("status"),
            "started_at": session.get("started_at"),
            "last_active_at": session.get("last_active_at"),
            "goal_count": len(goals),
            "entity_count": len(entities),
            "tactic_count": len(tactics),
        })

    return {
        "sessions": sessions,
        "stats": {
            "active_sessions": len([s for s in sessions if s["status"] == "active"]),
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
        },
    }


@memory_router.get("/l0/workbench/{session_id}")
async def get_l0_workbench(session_id: str):
    """Get the workbench (goals, entities, tactics) for a session."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="L0 working memory not initialized",
        )

    workbench = await unified_memory.l0.get_workbench(session_id)
    if not workbench.get("session"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return workbench


# =============================================================================
# L2 Cognition Endpoints
# =============================================================================

@memory_router.get("/l2/statistics")
async def get_l2_statistics():
    """Get L2 cognition statistics."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"relation_count": 0, "assertion_count": 0, "db_path": None}

    relations = await unified_memory.l2.get_relationships(limit=10000)
    assertions = await unified_memory.l2.list_tom_assertions(limit=10000)
    return {
        "relation_count": len(relations),
        "assertion_count": len(assertions),
        "db_path": unified_memory.l2.db_path,
    }


@memory_router.get("/l2/relations")
async def list_l2_relations(limit: int = Query(default=100, ge=1, le=500)):
    """List knowledge graph relations."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []
    return await unified_memory.l2.get_relationships(limit=limit)


@memory_router.get("/l2/assertions")
async def list_l2_assertions(limit: int = Query(default=100, ge=1, le=500)):
    """List ToM trait assertions."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []
    return await unified_memory.l2.list_tom_assertions(limit=limit)


# =============================================================================
# L3 Reflection Endpoints
# =============================================================================

@memory_router.get("/l3/summaries")
async def list_l3_summaries(
    limit: int = Query(default=100, ge=1, le=500),
    summary_type: Optional[str] = Query(default=None, description="Filter by type: temporal, thematic, insight"),
):
    """List L3 reflection summaries."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l3:
        return []

    summaries = await unified_memory.l3.list_summaries(limit=limit)
    if summary_type:
        summaries = [s for s in summaries if s.get("summary_type") == summary_type]
    return summaries


# =============================================================================
# Unified Statistics Endpoint
# =============================================================================

@memory_router.get("/statistics")
async def get_memory_statistics():
    """Return per-layer memory statistics in L0-L4 format."""
    unified_memory = _resolve_unified_memory()
    memory_integration = _resolve_memory_integration()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    stats: Dict[str, Any] = {}

    # L0 statistics
    if unified_memory.l0:
        sessions = unified_memory.l0._sessions
        total_goals = sum(len(unified_memory.l0._goal_stack.get(sid, [])) for sid in sessions)
        total_entities = sum(len(unified_memory.l0._active_entities.get(sid, {})) for sid in sessions)
        total_tactics = sum(len(unified_memory.l0._temporary_tactics.get(sid, {})) for sid in sessions)
        stats["l0"] = {
            "active_sessions": len([s for s in sessions.values() if s.get("status") == "active"]),
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
            "db_path": unified_memory.l0.checkpoint_db_path,
        }
    else:
        stats["l0"] = {"active_sessions": 0, "total_goals": 0, "total_entities": 0, "total_tactics": 0}

    # L1 statistics
    if unified_memory.l1:
        stats["l1"] = {
            "event_count": await unified_memory.l1.count_events(),
            "db_path": unified_memory.l1.db_path,
        }
    else:
        stats["l1"] = {"event_count": 0}

    # L2 statistics
    if unified_memory.l2:
        relations = await unified_memory.l2.get_relationships(limit=10000)
        assertions = await unified_memory.l2.list_tom_assertions(limit=10000)
        stats["l2"] = {
            "relation_count": len(relations),
            "assertion_count": len(assertions),
            "db_path": unified_memory.l2.db_path,
        }
    else:
        stats["l2"] = {"relation_count": 0, "assertion_count": 0}

    # L3 statistics
    if unified_memory.l3:
        summaries = await unified_memory.l3.list_summaries(limit=10000)
        stats["l3"] = {
            "summary_count": len(summaries),
            "db_path": unified_memory.l3.db_path,
        }
    else:
        stats["l3"] = {"summary_count": 0}

    # L4 statistics
    if unified_memory.l4:
        skills = await unified_memory.l4.get_all_skills(limit=10000)
        open_breakers = sum(1 for s in skills if s.get("circuit_breaker_state") != "closed")
        stats["l4"] = {
            "skill_count": len(skills),
            "open_circuit_breakers": open_breakers,
            "db_path": unified_memory.l4.db_path,
        }
    else:
        stats["l4"] = {"skill_count": 0, "open_circuit_breakers": 0}

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
    unified_memory = _resolve_unified_memory()
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
    unified_memory = _resolve_unified_memory()
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
    unified_memory = _resolve_unified_memory()
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
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognition store unavailable",
        )

    snapshot = await unified_memory.l2.get_tom_snapshot(entity_id=entity_id, entity_type=entity_type)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return snapshot
