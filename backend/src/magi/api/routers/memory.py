"""
记忆管理API路由

提供 L1-L5 五层记忆架构的查询接口：
- L1: 原始事件存储
- L2: 事件关系图
- L3: 语义搜索
- L4: 时间摘要
- L5: 能力列表
"""
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

memory_router = APIRouter()


# ============ 数据模型 ============

class MemoryResponse(BaseModel):
    """记忆响应"""
    id: str
    type: str
    content: Dict[str, Any]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None


class MemorySearchRequest(BaseModel):
    """记忆搜索请求"""
    query: str = Field(..., description="搜索查询")
    memory_type: Optional[str] = Field(None, description="记忆类型")
    limit: int = Field(default=10, description="返回数量限制")


class SemanticSearchRequest(BaseModel):
    """语义搜索请求"""
    query: str = Field(..., description="搜索查询文本")
    search_type: str = Field(default="hybrid", description="搜索类型: hybrid, semantic, keyword, relation")
    limit: int = Field(default=10, ge=1, le=100, description="返回数量限制")


class SemanticSearchResult(BaseModel):
    """语义搜索结果"""
    event_id: str
    similarity: float = Field(..., description="相似度分数")
    text: str = Field(..., description="事件文本")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventContextResponse(BaseModel):
    """事件上下文响应"""
    event_id: str
    depth: int
    related_events: Dict[int, List[Dict[str, Any]]]


class SummaryResponse(BaseModel):
    """摘要响应"""
    period_type: str
    period_key: str
    start_time: float
    end_time: float
    event_count: int
    summary: str
    event_types: Dict[str, int]
    metrics: Dict[str, Any]


class CapabilityResponse(BaseModel):
    """能力响应"""
    capability_id: str
    name: str
    description: str
    success_rate: float
    usage_count: int
    avg_duration: float
    last_used: float


class MemoryStatisticsResponse(BaseModel):
    """记忆统计响应"""
    l1_raw: Dict[str, Any]
    l2_relations: Dict[str, Any]
    l3_embeddings: Optional[Dict[str, Any]] = None
    l4_summaries: Optional[Dict[str, Any]] = None
    l5_capabilities: Optional[Dict[str, Any]] = None
    integration_stats: Optional[Dict[str, Any]] = None


# ============ 辅助函数 ============

def get_unified_memory():
    """获取统一记忆存储实例"""
    try:
        from ...agent import get_unified_memory
        return get_unified_memory()
    except RuntimeError:
        return None


def get_memory_integration():
    """获取记忆集成模块实例"""
    try:
        from ...agent import get_memory_integration
        return get_memory_integration()
    except RuntimeError:
        return None


# ============ L1-L5 API 端点 ============

@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = Query(default=50, ge=1, le=500, description="返回数量限制"),
    event_type: Optional[str] = Query(None, description="过滤事件类型"),
):
    """
    获取 L1 原始事件列表

    Args:
        limit: 返回数量限制
        event_type: 过滤事件类型

    Returns:
        事件列表和统计信息
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

        # 获取事件（从 event_store 表）
        events = []
        async with aiosqlite.connect(unified_memory.l1_raw._expanded_db_path) as db:
            if event_type:
                cursor = await db.execute("""
                    SELECT id, type, data, timestamp, source, level, correlation_id, metadata
                    FROM event_store
                    WHERE type = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (event_type, limit))
            else:
                cursor = await db.execute("""
                    SELECT id, type, data, timestamp, source, level, correlation_id, metadata
                    FROM event_store
                    ORDER BY timestamp DESC
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

        # 获取总数
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
    获取 L2 关系统计信息

    Returns:
        关系统计信息
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
    获取 L1-L5 所有层级的统计信息

    Returns:
        记忆统计信息
    """
    unified_memory = get_unified_memory()
    memory_integration = get_memory_integration()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    stats = unified_memory.get_statistics()

    # 添加集成模块统计
    if memory_integration:
        stats["integration_stats"] = memory_integration.get_statistics()

    return stats


@memory_router.post("/search", response_model=List[SemanticSearchResult])
async def semantic_search(request: SemanticSearchRequest):
    """
    语义搜索 (L3)

    使用向量嵌入进行语义相似度搜索

    Args:
        request: 搜索请求

    Returns:
        搜索结果列表
    """
    unified_memory = get_unified_memory()

    if not unified_memory or not unified_memory.l3_embeddings:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search not available (L3 embeddings disabled)",
        )

    try:
        results = await unified_memory.search(
            query=request.query,
            search_type=request.search_type,
            limit=request.limit,
        )

        # 转换为响应格式
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}",
        )


@memory_router.get("/event/{event_id}/context", response_model=EventContextResponse)
async def get_event_context(
    event_id: str,
    max_depth: int = Query(default=2, ge=1, le=5, description="最大深度"),
):
    """
    获取事件上下文 (L2)

    获取指定事件的相关事件（基于关系图）

    Args:
        event_id: 事件ID
        max_depth: 最大深度

    Returns:
        事件上下文
    """
    unified_memory = get_unified_memory()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    try:
        context = unified_memory.get_related_events(
            event_id=event_id,
            max_depth=max_depth,
        )

        return EventContextResponse(
            event_id=event_id,
            depth=max_depth,
            related_events=context,
        )
    except Exception as e:
        logger.error(f"Failed to get event context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get event context: {str(e)}",
        )


@memory_router.get("/summary/{period_type}", response_model=Optional[SummaryResponse])
async def get_summary(
    period_type: str,
    period_key: Optional[str] = Query(None, description="时间窗口标识（默认为当前）"),
    force_generate: bool = Query(False, description="是否强制重新生成"),
):
    """
    获取时间摘要 (L4)

    获取指定时间窗口的事件摘要

    Args:
        period_type: 时间粒度（hour/day/week/month）
        period_key: 时间窗口标识（默认为当前）
        force_generate: 是否强制重新生成

    Returns:
        事件摘要
    """
    # 验证 period_type
    valid_period_types = {"hour", "day", "week", "month"}
    if period_type not in valid_period_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid period_type '{period_type}'. Must be one of: {', '.join(valid_period_types)}",
        )

    unified_memory = get_unified_memory()

    if not unified_memory or not unified_memory.l4_summaries:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Summary service not available (L4 summaries disabled)",
        )

    try:
        # 如果强制生成，使用 generate_summary
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get summary: {str(e)}",
        )


@memory_router.get("/capabilities", response_model=List[CapabilityResponse])
async def get_capabilities(
    limit: int = Query(default=50, ge=1, le=200, description="返回数量限制"),
):
    """
    获取能力列表 (L5)

    获取所有已提取的能力

    Args:
        limit: 返回数量限制

    Returns:
        能力列表
    """
    unified_memory = get_unified_memory()

    if not unified_memory or not unified_memory.l5_capabilities:
        return []

    try:
        capabilities = unified_memory.l5_capabilities.get_all_capabilities()

        # 按使用次数排序
        capabilities.sort(key=lambda c: c.usage_count, reverse=True)

        # 限制数量
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get capabilities: {str(e)}",
        )


@memory_router.get("/capabilities/{capability_id}", response_model=CapabilityResponse)
async def get_capability(capability_id: str):
    """
    获取单个能力详情 (L5)

    Args:
        capability_id: 能力ID

    Returns:
        能力详情
    """
    unified_memory = get_unified_memory()

    if not unified_memory or not unified_memory.l5_capabilities:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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
    手动生成所有待处理的摘要 (L4)

    Returns:
        生成结果
    """
    memory_integration = get_memory_integration()

    if not memory_integration:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate summaries: {str(e)}",
        )


@memory_router.delete("/capabilities/{capability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capability(capability_id: str):
    """
    删除能力 (L5)

    Args:
        capability_id: 能力ID
    """
    unified_memory = get_unified_memory()

    if not unified_memory or not unified_memory.l5_capabilities:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Capability service not available",
        )

    success = unified_memory.l5_capabilities.delete_capability(capability_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability {capability_id} not found",
        )


# ============ 兼容旧版 API 端点 ============

# 内存存储（开发用）
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
    获取记忆列表（旧版 API）

    Args:
        memory_type: 过滤记忆类型
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        记忆列表
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
    获取记忆详情（旧版 API）

    Args:
        memory_id: 记忆ID

    Returns:
        记忆详情
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
    删除记忆（旧版 API）

    Args:
        memory_id: 记忆ID
    """
    if memory_id not in _legacy_memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found",
        )

    del _legacy_memory_store[memory_id]
    logger.info(f"Deleted memory: {memory_id}")
