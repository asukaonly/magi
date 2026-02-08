"""
记忆管理API路由

提供记忆的搜索、详情、删除等功能
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


# ============ 内存存储（开发用） ============

_memory_store: Dict[str, Dict] = {
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


# ============ API端点 ============

@memory_router.get("/", response_model=List[MemoryResponse])
async def list_memories(
    memory_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    获取记忆列表

    Args:
        memory_type: 过滤记忆类型
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        记忆列表
    """
    memories = list(_memory_store.values())

    # 过滤
    if memory_type:
        memories = [m for m in memories if m["type"] == memory_type]

    # 排序（按创建时间倒序）
    memories.sort(key=lambda x: x["created_at"], reverse=True)

    # 分页
    memories = memories[offset:offset + limit]

    return memories


@memory_router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: str):
    """
    获取记忆详情

    Args:
        memory_id: 记忆ID

    Returns:
        记忆详情
    """
    if memory_id not in _memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found",
        )

    return _memory_store[memory_id]


@memory_router.post("/search")
async def search_memories(request: MemorySearchRequest):
    """
    搜索记忆

    Args:
        request: 搜索请求

    Returns:
        搜索结果
    """
    memories = list(_memory_store.values())

    # 过滤类型
    if request.memory_type:
        memories = [m for m in memories if m["type"] == request.memory_type]

    # 简单搜索（包含查询字符串）
    query = request.query.lower()
    results = [
        m for m in memories
        if query in str(m["content"]).lower()
    ]

    # 限制数量
    results = results[:request.limit]

    return {
        "success": True,
        "data": results,
        "total": len(results),
    }


@memory_router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: str):
    """
    删除记忆

    Args:
        memory_id: 记忆ID
    """
    if memory_id not in _memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found",
        )

    del _memory_store[memory_id]
    logger.info(f"Deleted memory: {memory_id}")


@memory_router.get("/stats/summary")
async def get_memory_stats():
    """
    获取记忆统计摘要

    Returns:
        记忆统计信息
    """
    total = len(_memory_store)
    self_memories = sum(1 for m in _memory_store.values() if m["type"] == "self")
    other_memories = sum(1 for m in _memory_store.values() if m["type"] == "other")

    return {
        "success": True,
        "data": {
            "total": total,
            "self": self_memories,
            "other": other_memories,
        },
    }
