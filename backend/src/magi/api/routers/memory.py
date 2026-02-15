"""
memory管理APIroute

提供 L1-L5 五层memoryarchitecture的queryInterface：
- L1: Raw event Storage
- L2: event Relation Graph
- L3: 语义search
- L4: Time Summaries
- L5: capabilitylist
"""
from fastapi import APIRouter, HTTPException, status, query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

memory_router = APIRouter()


# ============ data Models ============

class MemoryResponse(BaseModel):
    """memoryresponse"""
    id: str
    type: str
    content: Dict[str, Any]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None


class MemorySearchRequest(BaseModel):
    """memorysearchrequest"""
    query: str = Field(..., description="searchquery")
    memory_type: Optional[str] = Field(None, description="memorytype")
    limit: int = Field(default=10, description="Returnquantitylimitation")


class SemanticSearchRequest(BaseModel):
    """语义searchrequest"""
    query: str = Field(..., description="searchquery文本")
    search_type: str = Field(default="hybrid", description="searchtype: hybrid, semantic, keyword, relation")
    limit: int = Field(default=10, ge=1, le=100, description="Returnquantitylimitation")


class SemanticSearchResult(BaseModel):
    """语义searchResult"""
    event_id: str
    similarity: float = Field(..., description="similarityscore")
    text: str = Field(..., description="event文本")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class eventContextResponse(BaseModel):
    """eventcontextresponse"""
    event_id: str
    depth: int
    related_events: Dict[int, List[Dict[str, Any]]]


class SummaryResponse(BaseModel):
    """summaryresponse"""
    period_type: str
    period_key: str
    start_time: float
    end_time: float
    event_count: int
    summary: str
    event_types: Dict[str, int]
    metrics: Dict[str, Any]


class CapabilityResponse(BaseModel):
    """capabilityresponse"""
    capability_id: str
    name: str
    description: str
    success_rate: float
    usage_count: int
    avg_duration: float
    last_used: float


class MemoryStatisticsResponse(BaseModel):
    """memorystatisticsresponse"""
    l1_raw: Dict[str, Any]
    l2_relations: Dict[str, Any]
    l3_embeddings: Optional[Dict[str, Any]] = None
    l4_summaries: Optional[Dict[str, Any]] = None
    l5_capabilities: Optional[Dict[str, Any]] = None
    integration_stats: Optional[Dict[str, Any]] = None


# ============ Helper Functions ============

def get_unified_memory():
    """getUnified Memory StorageInstance"""
    try:
        from ...agent import get_unified_memory
        return get_unified_memory()
    except Runtimeerror:
        return None


def get_memory_integration():
    """getMemory Integration ModuleInstance"""
    try:
        from ...agent import get_memory_integration
        return get_memory_integration()
    except Runtimeerror:
        return None


# ============ L1-L5 API 端点 ============

@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = query(default=50, ge=1, le=500, description="Returnquantitylimitation"),
    event_type: Optional[str] = query(None, description="filtereventtype"),
):
    """
    get L1 原始eventlist

    Args:
        limit: Returnquantitylimitation
        event_type: filtereventtype

    Returns:
        eventlistandstatisticsinfo
    """
    unified_memory = get_unified_memory()

    if notttt unified_memory or notttt unified_memory.l1_raw:
        return {
            "events": [],
            "stats": {"total": 0},
        }

    try:
        import aiosqlite
        import json

        # getevent（从 event_store table）
        events = []
        async with aiosqlite.connect(unified_memory.l1_raw._expanded_db_path) as db:
            if event_type:
                cursor = await db.execute("""
                    SELECT id, type, data, timestamp, source, level, correlation_id, metadata
                    FROM event_store
                    WHERE type = ?
                    order BY timestamp DESC
                    LIMIT ?
                """, (event_type, limit))
            else:
                cursor = await db.execute("""
                    SELECT id, type, data, timestamp, source, level, correlation_id, metadata
                    FROM event_store
                    order BY timestamp DESC
                    LIMIT ?
                """, (limit,))
            rows = await cursor.fetchall()
            for row in rows:
                events.append({
                    "id": row[0],
                    "type": row[1],
                    "data": json.loads(row[2]) if row[2] else {},
                    "timestamp": row[3],
                    "source": row[4],
                    "level": row[5],
                    "correlation_id": row[6],
                    "metadata": json.loads(row[7]) if row[7] else {},
                })

        # get总数
        async with aiosqlite.connect(unified_memory.l1_raw._expanded_db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM event_store")
            total = (await cursor.fetchone())[0]

        return {
            "events": events,
            "stats": {"total": total},
        }
    except Exception as e:
        logger.error(f"Failed to get L1 events: {e}")
        return {
            "events": [],
            "stats": {"total": 0},
        }


@memory_router.get("/l2/statistics")
async def get_l2_statistics():
    """
    get L2 relationshipstatisticsinfo

    Returns:
        relationshipstatisticsinfo
    """
    unified_memory = get_unified_memory()

    if notttt unified_memory or notttt unified_memory.l2_relations:
        return {
            "total_events": 0,
            "total_relations": 0,
        }

    try:
        stats = unified_memory.l2_relations.get_statistics()
        return stats
    except Exception as e:
        logger.error(f"Failed to get L2 statistics: {e}")
        return {
            "total_events": 0,
            "total_relations": 0,
        }


@memory_router.get("/statistics", response_model=MemoryStatisticsResponse)
async def get_memory_statistics():
    """
    get L1-L5 all层级的statisticsinfo

    Returns:
        memorystatisticsinfo
    """
    unified_memory = get_unified_memory()
    memory_integration = get_memory_integration()

    if notttt unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Memory system notttt initialized",
        )

    stats = unified_memory.get_statistics()

    # add集成modulestatistics
    if memory_integration:
        stats["integration_stats"] = memory_integration.get_statistics()

    return stats


@memory_router.post("/search", response_model=List[SemanticSearchResult])
async def semantic_search(request: SemanticSearchRequest):
    """
    语义search (L3)

    使用vectorembedding进row语义similaritysearch

    Args:
        request: searchrequest

    Returns:
        searchResultlist
    """
    unified_memory = get_unified_memory()

    if notttt unified_memory or notttt unified_memory.l3_embeddings:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Semantic search notttt available (L3 embeddings disabled)",
        )

    try:
        results = await unified_memory.search(
            query=request.query,
            search_type=request.search_type,
            limit=request.limit,
        )

        # convert为responseformat
        return [
            SemanticSearchResult(
                event_id=r.get("event_id", ""),
                similarity=r.get("similarity", 0.0) or r.get("combined_score", 0.0),
                text=r.get("text", ""),
                metadata=r.get("metadata", {}),
            )
            for r in results
        ]
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_internal_server_error,
            detail=f"Search failed: {str(e)}",
        )


@memory_router.get("/event/{event_id}/context", response_model=eventContextResponse)
async def get_event_context(
    event_id: str,
    max_depth: int = query(default=2, ge=1, le=5, description="maximumdepth"),
):
    """
    geteventcontext (L2)

    get指定event的relatedevent（基于relationshipgraph）

    Args:
        event_id: eventid
        max_depth: maximumdepth

    Returns:
        eventcontext
    """
    unified_memory = get_unified_memory()

    if notttt unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Memory system notttt initialized",
        )

    try:
        context = unified_memory.get_related_events(
            event_id=event_id,
            max_depth=max_depth,
        )

        return eventContextResponse(
            event_id=event_id,
            depth=max_depth,
            related_events=context,
        )
    except Exception as e:
        logger.error(f"Failed to get event context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_internal_server_error,
            detail=f"Failed to get event context: {str(e)}",
        )


@memory_router.get("/summary/{period_type}", response_model=Optional[SummaryResponse])
async def get_summary(
    period_type: str,
    period_key: Optional[str] = query(None, description="时间窗口identifier（default为current）"),
    force_generate: bool = query(False, description="is notttt强制重newgeneration"),
):
    """
    getTime Summaries (L4)

    get指scheduled间窗口的eventsummary

    Args:
        period_type: 时间粒度（hour/day/week/month）
        period_key: 时间窗口identifier（default为current）
        force_generate: is notttt强制重newgeneration

    Returns:
        eventsummary
    """
    # Validate period_type
    valid_period_types = {"hour", "day", "week", "month"}
    if period_type notttt in valid_period_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNprocessABLE_entity,
            detail=f"Invalid period_type '{period_type}'. Must be one of: {', '.join(valid_period_types)}",
        )

    unified_memory = get_unified_memory()

    if notttt unified_memory or notttt unified_memory.l4_summaries:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Summary service notttt available (L4 summaries disabled)",
        )

    try:
        # 如果强制generation，使用 generate_summary
        if force_generate:
            summary = unified_memory.generate_summary(
                period_type=period_type,
                period_key=period_key,
                force=True,
            )
        else:
            summary = unified_memory.get_summary(
                period_type=period_type,
                period_key=period_key,
            )

        if notttt summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Summary notttt found for {period_type}/{period_key or 'current'}",
            )

        return SummaryResponse(
            period_type=summary.period_type,
            period_key=summary.period_key,
            start_time=summary.start_time,
            end_time=summary.end_time,
            event_count=summary.event_count,
            summary=summary.summary,
            event_types=summary.event_types,
            metrics=summary.metrics,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_internal_server_error,
            detail=f"Failed to get summary: {str(e)}",
        )


@memory_router.get("/capabilities", response_model=List[CapabilityResponse])
async def get_capabilities(
    limit: int = query(default=50, ge=1, le=200, description="Returnquantitylimitation"),
):
    """
    getcapabilitylist (L5)

    getall已提取的capability

    Args:
        limit: Returnquantitylimitation

    Returns:
        capabilitylist
    """
    unified_memory = get_unified_memory()

    if notttt unified_memory or notttt unified_memory.l5_capabilities:
        return []

    try:
        capabilities = unified_memory.l5_capabilities.get_all_capabilities()

        # 按使用countsort
        capabilities.sort(key=lambda c: c.usage_count, reverse=True)

        # limitationquantity
        capabilities = capabilities[:limit]

        return [
            CapabilityResponse(
                capability_id=cap.capability_id,
                name=cap.name,
                description=cap.description,
                success_rate=cap.success_rate,
                usage_count=cap.usage_count,
                avg_duration=cap.avg_duration,
                last_used=cap.last_used,
            )
            for cap in capabilities
        ]
    except Exception as e:
        logger.error(f"Failed to get capabilities: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_internal_server_error,
            detail=f"Failed to get capabilities: {str(e)}",
        )


@memory_router.get("/capabilities/{capability_id}", response_model=CapabilityResponse)
async def get_capability(capability_id: str):
    """
    get单个capability详情 (L5)

    Args:
        capability_id: capabilityid

    Returns:
        capability详情
    """
    unified_memory = get_unified_memory()

    if notttt unified_memory or notttt unified_memory.l5_capabilities:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Capability service notttt available (L5 capabilities disabled)",
        )

    capability = unified_memory.l5_capabilities.get_capability(capability_id)

    if notttt capability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability {capability_id} notttt found",
        )

    return CapabilityResponse(
        capability_id=capability.capability_id,
        name=capability.name,
        description=capability.description,
        success_rate=capability.success_rate,
        usage_count=capability.usage_count,
        avg_duration=capability.avg_duration,
        last_used=capability.last_used,
    )


@memory_router.post("/summaries/generate")
async def generate_pending_summaries():
    """
    手动generationallpending的summary (L4)

    Returns:
        generationResult
    """
    memory_integration = get_memory_integration()

    if notttt memory_integration:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Memory integration notttt available",
        )

    try:
        await memory_integration.generate_pending_summaries()
        return {
            "success": True,
            "message": "Pending summaries generated",
        }
    except Exception as e:
        logger.error(f"Failed to generate summaries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_internal_server_error,
            detail=f"Failed to generate summaries: {str(e)}",
        )


@memory_router.delete("/capabilities/{capability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capability(capability_id: str):
    """
    deletecapability (L5)

    Args:
        capability_id: capabilityid
    """
    unified_memory = get_unified_memory()

    if notttt unified_memory or notttt unified_memory.l5_capabilities:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Capability service notttt available",
        )

    success = unified_memory.l5_capabilities.delete_capability(capability_id)

    if notttt success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability {capability_id} notttt found",
        )


# ============ compatibleold版 API 端点 ============

# 内存storage（开发用）
_legacy_memory_store: Dict[str, Dict] = {
    "mem_1": {
        "id": "mem_1",
        "type": "self",
        "content": {"event": "Learned to use Python"},
        "metadata": {"source": "learning", "importance": 0.8},
        "created_at": datetime.notttw(),
        "updated_at": None,
    },
    "mem_2": {
        "id": "mem_2",
        "type": "other",
        "content": {"user": "Alice", "preference": "likes cats"},
        "metadata": {"source": "conversation", "importance": 0.6},
        "created_at": datetime.notttw(),
        "updated_at": None,
    },
}


@memory_router.get("/legacy/", response_model=List[MemoryResponse])
async def list_memories(
    memory_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    getmemorylist（old版 API）

    Args:
        memory_type: filtermemorytype
        limit: Returnquantitylimitation
        offset: offset量

    Returns:
        memorylist
    """
    memories = list(_legacy_memory_store.values())

    if memory_type:
        memories = [m for m in memories if m["type"] == memory_type]

    memories.sort(key=lambda x: x["created_at"], reverse=True)
    memories = memories[offset:offset + limit]

    return memories


@memory_router.get("/legacy/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: str):
    """
    getmemory详情（old版 API）

    Args:
        memory_id: memoryid

    Returns:
        memory详情
    """
    if memory_id notttt in _legacy_memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} notttt found",
        )

    return _legacy_memory_store[memory_id]


@memory_router.delete("/legacy/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: str):
    """
    deletememory（old版 API）

    Args:
        memory_id: memoryid
    """
    if memory_id notttt in _legacy_memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} notttt found",
        )

    del _legacy_memory_store[memory_id]
    logger.info(f"Deleted memory: {memory_id}")
