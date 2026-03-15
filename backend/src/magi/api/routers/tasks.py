"""
Task Management API Routes

Provides task creation, query, retry, and other functions.
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

tasks_router = APIRouter()


# ============ Data Models ============

class TaskCreateRequest(BaseModel):
    """Create task request"""

    type: str = Field(..., description="Task type")
    data: Dict[str, Any] = Field(default_factory=dict, description="Task data")
    priority: str = Field(default="normal", description="Task priority: low/normal/high")
    assignee: Optional[str] = Field(None, description="Assigned executor agent ID")


class TaskResponse(BaseModel):
    """Task response"""

    id: str
    type: str
    data: Dict[str, Any]
    priority: str
    status: str
    assignee: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TaskRetryRequest(BaseModel):
    """Retry task request"""

    retry_count: int = Field(default=1, description="Retry count")


# ============ In-memory storage (development use) ============

_tasks_store: Dict[str, Dict] = {}


# ============ API Endpoints ============

@tasks_router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    Get task list

    Args:
        status: Filter by task state
        priority: Filter by task priority
        assignee: Filter by executor agent
        limit: Return count limit
        offset: Offset

    Returns:
        Task list
    """
    tasks = list(_tasks_store.values())

    # filter
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if priority:
        tasks = [t for t in tasks if t["priority"] == priority]
    if assignee:
        tasks = [t for t in tasks if t["assignee"] == assignee]

    # Sort (by creation time, descending)
    tasks.sort(key=lambda x: x["created_at"], reverse=True)

    # Pagination
    total = len(tasks)
    tasks = tasks[offset:offset + limit]

    return tasks


@tasks_router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """
    Get task details

    Args:
        task_id: Task ID

    Returns:
        Task details
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
    Create task

    Args:
        request: Create request

    Returns:
        Created task
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
    Retry task

    Args:
        task_id: Task ID
        request: Retry request

    Returns:
        Retry result
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

    # Reset task state
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
    Delete task

    Args:
        task_id: Task ID
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
    Get task statistics summary

    Returns:
        Task statistics
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
