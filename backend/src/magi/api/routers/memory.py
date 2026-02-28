"""
memory管理APIroute

提供 L1-L5 五层memoryarchitecture的queryInterface：
- L1: Raw event Storage
- L2: event Relation Graph
- L3: 语义search
- L4: Time Summaries
- L5: capabilitylist
"""
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio
from pathlib import Path
import time

from ..services import get_chat_read_service
from ...core.logger import get_logger

logger = get_logger(__name__)

memory_router = APIRouter()

_model_download_jobs: Dict[str, Dict[str, Any]] = {}


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


class ModelDownloadRequest(BaseModel):
    model: str = Field(..., description="Embedding model name")


class ModelDownloadStatusResponse(BaseModel):
    model: str
    status: str
    progress: int
    message: Optional[str] = None
    updated_at: float


class InstalledModelsResponse(BaseModel):
    models: List[str]


# ============ Helper Functions ============

def get_unified_memory():
    """getUnified Memory StorageInstance"""
    try:
        from ...agent import get_unified_memory
        return get_unified_memory()
    except RuntimeError:
        return None


def get_memory_integration():
    """getMemory Integration ModuleInstance"""
    try:
        from ...agent import get_memory_integration
        return get_memory_integration()
    except RuntimeError:
        return None


def _get_models_dir() -> Path:
    models_dir = Path.home() / ".magi" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def _model_ready_file(model_name: str) -> Path:
    normalized = model_name.replace("/", "__")
    return _get_models_dir() / f"{normalized}.ready"


async def _simulate_model_download(model_name: str):
    steps = [10, 25, 45, 65, 80, 100]
    for progress in steps:
        await asyncio.sleep(0.4)
        _model_download_jobs[model_name] = {
            "status": "downloading" if progress < 100 else "ready",
            "progress": progress,
            "updated_at": time.time(),
            "message": "Downloading embedding model" if progress < 100 else "Model ready",
        }
    _model_ready_file(model_name).write_text(str(time.time()), encoding="utf-8")


# ============ L1-L5 API 端点 ============

@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = Query(default=50, ge=1, le=500, description="Returnquantitylimitation"),
    event_type: Optional[str] = Query(None, description="filtereventtype"),
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

    if not unified_memory or not unified_memory.l1_raw:
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
                    SELECT id, Type, data, timestamp, source, level, correlation_id, metadata
                    FROM event_store
                    WHERE type = ?
                    order BY timestamp DESC
                    LIMIT ?
                """, (event_type, limit))
            else:
                cursor = await db.execute("""
                    SELECT id, Type, data, timestamp, source, level, correlation_id, metadata
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

    if not unified_memory or not unified_memory.l2_relations:
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

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Memory system not initialized",
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

    if not unified_memory or not unified_memory.l3_embeddings:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Semantic search not available (L3 embeddings disabled)",
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
    max_depth: int = Query(default=2, ge=1, le=5, description="maximumdepth"),
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

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Memory system not initialized",
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
    period_key: Optional[str] = Query(None, description="时间窗口identifier（default为current）"),
    force_generate: bool = Query(False, description="is not强制重newgeneration"),
):
    """
    getTime Summaries (L4)

    get指scheduled间窗口的eventsummary

    Args:
        period_type: 时间粒度（hour/day/week/month）
        period_key: 时间窗口identifier（default为current）
        force_generate: is not强制重newgeneration

    Returns:
        eventsummary
    """
    # Validate period_type
    valid_period_types = {"hour", "day", "week", "month"}
    if period_type not in valid_period_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNprocessABLE_entity,
            detail=f"Invalid period_type '{period_type}'. Must be one of: {', '.join(valid_period_types)}",
        )

    unified_memory = get_unified_memory()

    if not unified_memory or not unified_memory.l4_summaries:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Summary service not available (L4 summaries disabled)",
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

        if not summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Summary not found for {period_type}/{period_key or 'current'}",
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
    limit: int = Query(default=50, ge=1, le=200, description="Returnquantitylimitation"),
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

    if not unified_memory or not unified_memory.l5_capabilities:
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

    if not unified_memory or not unified_memory.l5_capabilities:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Capability service not available (L5 capabilities disabled)",
        )

    capability = unified_memory.l5_capabilities.get_capability(capability_id)

    if not capability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability {capability_id} not found",
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

    if not memory_integration:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Memory integration not available",
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

    if not unified_memory or not unified_memory.l5_capabilities:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Capability service not available",
        )

    success = unified_memory.l5_capabilities.delete_capability(capability_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability {capability_id} not found",
        )


# ============ Embedding model management ============

@memory_router.post("/models/download", response_model=ModelDownloadStatusResponse)
async def download_embedding_model(request: ModelDownloadRequest):
    model = request.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model is required")

    if _model_ready_file(model).exists():
        status_obj = {
            "status": "ready",
            "progress": 100,
            "updated_at": time.time(),
            "message": "Model already installed",
        }
        _model_download_jobs[model] = status_obj
        return ModelDownloadStatusResponse(model=model, **status_obj)

    existing = _model_download_jobs.get(model)
    if existing and existing.get("status") == "downloading":
        return ModelDownloadStatusResponse(model=model, **existing)

    _model_download_jobs[model] = {
        "status": "downloading",
        "progress": 0,
        "updated_at": time.time(),
        "message": "Download started",
    }
    asyncio.create_task(_simulate_model_download(model))
    return ModelDownloadStatusResponse(model=model, **_model_download_jobs[model])


@memory_router.get("/models/download/{model_name}/status", response_model=ModelDownloadStatusResponse)
async def get_embedding_model_status(model_name: str):
    if _model_ready_file(model_name).exists():
        status_obj = {
            "status": "ready",
            "progress": 100,
            "updated_at": time.time(),
            "message": "Model installed",
        }
        _model_download_jobs[model_name] = status_obj
        return ModelDownloadStatusResponse(model=model_name, **status_obj)

    status_obj = _model_download_jobs.get(model_name)
    if status_obj:
        return ModelDownloadStatusResponse(model=model_name, **status_obj)

    return ModelDownloadStatusResponse(
        model=model_name,
        status="not_downloaded",
        progress=0,
        updated_at=time.time(),
        message="Model not downloaded",
    )


@memory_router.get("/models", response_model=InstalledModelsResponse)
async def list_installed_embedding_models():
    models = [p.stem.replace("__", "/") for p in _get_models_dir().glob("*.ready")]
    return InstalledModelsResponse(models=sorted(models))


# ============ Memory Clear API ============

@memory_router.delete("/clear")
async def clear_all_memories():
    """
    清除所有记忆数据（L1-L5）和对话上下文

    警告：此操作不可恢复，将清除：
    - L1: 所有原始事件
    - L2: 所有事件关系
    - L3: 所有语义嵌入
    - L4: 所有摘要
    - L5: 所有能力记录
    - Chat 会话映射与历史查询上下文

    Returns:
        清除结果
    """
    import aiosqlite

    unified_memory = get_unified_memory()

    results = {
        "l1_raw": {"cleared": False, "count": 0},
        "l2_relations": {"cleared": False, "count": 0},
        "l3_embeddings": {"cleared": False, "count": 0},
        "l4_summaries": {"cleared": False, "count": 0},
        "l5_capabilities": {"cleared": False, "count": 0},
        "chat_context": {"cleared": False, "count": 0},
    }

    errors = []

    # L1: 清除原始事件
    try:
        if unified_memory and unified_memory.l1_raw:
            async with aiosqlite.connect(unified_memory.l1_raw._expanded_db_path) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM event_store")
                count = (await cursor.fetchone())[0]
                await db.execute("DELETE FROM event_store")
                await db.commit()
                results["l1_raw"] = {"cleared": True, "count": count}
    except Exception as e:
        errors.append(f"L1: {str(e)}")

    # L2: 清除事件关系
    try:
        if unified_memory and unified_memory.l2_relations:
            count = len(unified_memory.l2_relations._events)
            unified_memory.l2_relations._events.clear()
            unified_memory.l2_relations._relations.clear()
            unified_memory.l2_relations._save()
            results["l2_relations"] = {"cleared": True, "count": count}
    except Exception as e:
        errors.append(f"L2: {str(e)}")

    # L3: 清除语义嵌入
    try:
        if unified_memory and unified_memory.l3_embeddings:
            stats = unified_memory.l3_embeddings.get_statistics()
            count = stats.get("total_embeddings", 0)
            unified_memory.l3_embeddings._embeddings.clear()
            unified_memory.l3_embeddings._event_texts.clear()
            unified_memory.l3_embeddings._save()
            results["l3_embeddings"] = {"cleared": True, "count": count}
    except Exception as e:
        errors.append(f"L3: {str(e)}")

    # L4: 清除摘要
    try:
        if unified_memory and unified_memory.l4_summaries:
            stats = unified_memory.l4_summaries.get_statistics()
            count = stats.get("total_summaries", 0)
            unified_memory.l4_summaries._summaries.clear()
            unified_memory.l4_summaries._event_buffers.clear()
            unified_memory.l4_summaries._save()
            results["l4_summaries"] = {"cleared": True, "count": count}
    except Exception as e:
        errors.append(f"L4: {str(e)}")

    # L5: 清除能力记录
    try:
        if unified_memory and unified_memory.l5_capabilities:
            stats = unified_memory.l5_capabilities.get_statistics()
            count = stats.get("total_capabilities", 0)
            unified_memory.l5_capabilities._capabilities.clear()
            unified_memory.l5_capabilities._task_history.clear()
            unified_memory.l5_capabilities._save()
            results["l5_capabilities"] = {"cleared": True, "count": count}
    except Exception as e:
        errors.append(f"L5: {str(e)}")

    # 清除用户态会话映射（运行态上下文不在 API 层直接清除）
    try:
        read_service = get_chat_read_service()
        session_count = read_service.clear_all_sessions()
        results["chat_context"] = {"cleared": True, "count": session_count}
        logger.info(f"Cleared chat session mappings: {session_count}")
    except Exception as e:
        errors.append(f"ChatContext: {str(e)}")

    if errors:
        logger.warning(f"Memory clear completed with errors: {errors}")
        return {
            "success": True,
            "results": results,
            "warnings": errors,
        }

    logger.info("All memories and chat context cleared successfully")
    return {
        "success": True,
        "results": results,
    }


# ============ compatibleold版 API 端点 ============

# 内存storage（开发用）
_legacy_memory_store: Dict[str, Dict] = {
    "mem_1": {
        "id": "mem_1",
        "type": "self",
        "content": {"event": "Learned to use Python"},
        "metadata": {"source": "learning", "importance": 0.8},
        "created_at": datetime.now(),
        "updated_at": None,
    },
    "mem_2": {
        "id": "mem_2",
        "type": "other",
        "content": {"user": "Alice", "preference": "likes cats"},
        "metadata": {"source": "conversation", "importance": 0.6},
        "created_at": datetime.now(),
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
    if memory_id not in _legacy_memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found",
        )

    return _legacy_memory_store[memory_id]


@memory_router.delete("/legacy/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: str):
    """
    deletememory（old版 API）

    Args:
        memory_id: memoryid
    """
    if memory_id not in _legacy_memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found",
        )

    del _legacy_memory_store[memory_id]
    logger.info(f"Deleted memory: {memory_id}")
