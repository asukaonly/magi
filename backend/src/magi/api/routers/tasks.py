"""Task (todo) management API router."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...tasks.models import TaskPriority, TaskStatus, UserTask
from ...tasks.store import TaskStore

tasks_router = APIRouter()

_store: TaskStore | None = None


def _get_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore()
    return _store


def configure_task_store(store: TaskStore) -> None:
    """Allow bootstrap to inject a pre-configured store."""
    global _store
    _store = store


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    priority: str = "medium"
    tags: list[str] = Field(default_factory=list)
    due_date: Optional[float] = None
    linked_orchestration_id: Optional[str] = None
    linked_turn_id: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[list[str]] = None
    due_date: Optional[float] = None
    linked_orchestration_id: Optional[str] = None
    linked_turn_id: Optional[str] = None


def _validate_status(raw: str) -> TaskStatus:
    try:
        return TaskStatus(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {raw}. Valid: {[s.value for s in TaskStatus]}",
        )


def _validate_priority(raw: str) -> TaskPriority:
    try:
        return TaskPriority(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid priority: {raw}. Valid: {[p.value for p in TaskPriority]}",
        )


@tasks_router.get("/")
async def list_tasks(
    user_id: str = Query(..., min_length=1),
    task_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List tasks for a user, optionally filtered by status."""
    if task_status:
        _validate_status(task_status)
    store = _get_store()
    tasks = await store.list_tasks(user_id=user_id, status=task_status, limit=limit, offset=offset)
    return {"tasks": [t.to_dict() for t in tasks]}


@tasks_router.get("/{task_id}")
async def get_task(task_id: str):
    """Get a single task by id."""
    store = _get_store()
    task = await store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return {"task": task.to_dict()}


@tasks_router.post("/", status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreateRequest, user_id: str = Query(..., min_length=1)):
    """Create a new task."""
    _validate_priority(body.priority)
    task = UserTask(
        task_id="",
        title=body.title,
        description=body.description,
        priority=TaskPriority(body.priority),
        tags=body.tags,
        due_date=body.due_date,
        created_by="user",
        user_id=user_id,
        linked_orchestration_id=body.linked_orchestration_id,
        linked_turn_id=body.linked_turn_id,
    )
    store = _get_store()
    created = await store.create_task(task)
    return {"task": created.to_dict()}


@tasks_router.patch("/{task_id}")
async def update_task(task_id: str, body: TaskUpdateRequest):
    """Partially update a task."""
    if body.status is not None:
        _validate_status(body.status)
    if body.priority is not None:
        _validate_priority(body.priority)
    store = _get_store()
    existing = await store.get_task(task_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # Build sentinel-aware kwargs.
    kwargs: dict[str, Any] = {}
    if body.title is not None:
        kwargs["title"] = body.title
    if body.description is not None:
        kwargs["description"] = body.description
    if body.status is not None:
        kwargs["status"] = body.status
    if body.priority is not None:
        kwargs["priority"] = body.priority
    if body.tags is not None:
        kwargs["tags"] = body.tags
    if body.due_date is not None:
        kwargs["due_date"] = body.due_date
    if body.linked_orchestration_id is not None:
        kwargs["linked_orchestration_id"] = body.linked_orchestration_id
    if body.linked_turn_id is not None:
        kwargs["linked_turn_id"] = body.linked_turn_id

    updated = await store.update_task(task_id, **kwargs)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found after update")
    return {"task": updated.to_dict()}


@tasks_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str):
    """Delete a task."""
    store = _get_store()
    deleted = await store.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


@tasks_router.get("/orchestration/{orchestration_id}")
async def list_tasks_by_orchestration(orchestration_id: str):
    """List tasks linked to a specific orchestration context."""
    store = _get_store()
    tasks = await store.list_by_orchestration(orchestration_id)
    return {"tasks": [t.to_dict() for t in tasks]}
