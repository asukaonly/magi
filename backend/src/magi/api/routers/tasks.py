"""
任务管理API路由

提供任务的创建、查询、重试等功能
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

tasks_router = APIRouter()


# ============ 数据模型 ============

class TaskCreateRequest(BaseModel):
    """创建任务请求"""

    type: str = Field(..., description="任务类型")
    data: Dict[str, Any] = Field(default_factory=dict, description="任务数据")
    priority: str = Field(default="normal", description="任务优先级: low/normal/high")
    assignee: Optional[str] = Field(None, description="指定执行Agent ID")


class TaskResponse(BaseModel):
    """任务响应"""

    id: str
    type: str
    data: Dict[str, Any]
    priority: str
    status: str
    assignee: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TaskRetryRequest(BaseModel):
    """重试任务请求"""

    retry_count: int = Field(default=1, description="重试次数")


# ============ 内存存储（开发用） ============

_tasks_store: Dict[str, Dict] = {}


# ============ API端点 ============

@tasks_router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    获取任务列表

    Args:
        status: 过滤任务状态
        priority: 过滤任务优先级
        assignee: 过滤执行Agent
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        任务列表
    """
    tasks = list(_tasks_store.values())

    # 过滤
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if priority:
        tasks = [t for t in tasks if t["priority"] == priority]
    if assignee:
        tasks = [t for t in tasks if t["assignee"] == assignee]

    # 排序（按创建时间倒序）
    tasks.sort(key=lambda x: x["created_at"], reverse=True)

    # 分页
    total = len(tasks)
    tasks = tasks[offset:offset + limit]

    return tasks


@tasks_router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """
    获取任务详情

    Args:
        task_id: 任务ID

    Returns:
        任务详情
    """
    if task_id not in _tasks_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    return _tasks_store[task_id]


@tasks_router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(request: TaskCreateRequest):
    """
    创建任务

    Args:
        request: 创建请求

    Returns:
        创建的任务
    """
    task_id = f"task_{len(_tasks_store) + 1}"

    task = {
        "id": task_id,
        "type": request.type,
        "data": request.data,
        "priority": request.priority,
        "status": "pending",
        "assignee": request.assignee,
        "created_at": datetime.now(),
        "updated_at": None,
    }

    _tasks_store[task_id] = task
    logger.info(f"Created task: {task_id}")

    return task


@tasks_router.post("/{task_id}/retry")
async def retry_task(task_id: str, request: TaskRetryRequest):
    """
    重试任务

    Args:
        task_id: 任务ID
        request: 重试请求

    Returns:
        重试结果
    """
    if task_id not in _tasks_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    task = _tasks_store[task_id]

    if task["status"] not in ["failed", "completed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} status is {task['status']}, cannot retry",
        )

    # 重置任务状态
    task["status"] = "pending"
    task["updated_at"] = datetime.now()

    logger.info(f"Retried task: {task_id} (count: {request.retry_count})")

    return {
        "success": True,
        "message": f"Task {task_id} queued for retry",
        "data": {
            "task_id": task_id,
            "retry_count": request.retry_count,
            "status": task["status"],
        },
    }


@tasks_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str):
    """
    删除任务

    Args:
        task_id: 任务ID
    """
    if task_id not in _tasks_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    del _tasks_store[task_id]
    logger.info(f"Deleted task: {task_id}")


@tasks_router.get("/stats/summary")
async def get_task_stats():
    """
    获取任务统计摘要

    Returns:
        任务统计信息
    """
    total = len(_tasks_store)
    pending = sum(1 for t in _tasks_store.values() if t["status"] == "pending")
    running = sum(1 for t in _tasks_store.values() if t["status"] == "running")
    completed = sum(1 for t in _tasks_store.values() if t["status"] == "completed")
    failed = sum(1 for t in _tasks_store.values() if t["status"] == "failed")

    return {
        "success": True,
        "data": {
            "total": total,
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
        },
    }
