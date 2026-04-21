"""Background task REST endpoints.

Mounted under ``/api/background-tasks`` via :func:`register_api_routes`.
All endpoints operate on the process-wide :class:`BackgroundTaskManager`
resolved through the DI container.

Endpoints:

* ``GET  /``                        — list + filter tasks
* ``GET  /{task_id}``               — one task + event log
* ``POST /{task_id}/cancel``        — request cancellation
* ``POST /{task_id}/retry``         — retry a terminal task
* ``POST /{task_id}/dismiss``       — soft-delete from the list
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...agent.background import BackgroundTaskStatus
from ...core.runtime_bindings import require_background_task_manager

background_tasks_router = APIRouter()


def _get_manager():
    try:
        return require_background_task_manager()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background task manager unavailable",
        ) from exc


def _serialize_task(task: Any) -> dict[str, Any]:
    return task.to_dict()


@background_tasks_router.get("")
async def list_background_tasks(
    user_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    status_filter: Optional[list[str]] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List background tasks, optionally filtered by user/session/status."""
    manager = _get_manager()
    statuses: Optional[list[BackgroundTaskStatus]] = None
    if status_filter:
        try:
            statuses = [BackgroundTaskStatus(value) for value in status_filter]
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status filter: {exc}",
            ) from exc
    tasks = await manager.store.list_tasks(
        user_id=user_id,
        session_id=session_id,
        statuses=statuses,
        limit=limit,
        offset=offset,
    )
    return {
        "tasks": [_serialize_task(task) for task in tasks],
        "active_count": manager.active_count(),
    }


@background_tasks_router.get("/{task_id}")
async def get_background_task(task_id: str) -> dict[str, Any]:
    """Return a single task plus its full event log."""
    manager = _get_manager()
    task = await manager.store.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Background task not found: {task_id}",
        )
    events = await manager.store.list_events(task_id)
    return {
        "task": _serialize_task(task),
        "events": [event.to_dict() for event in events],
    }


class CancelBackgroundTaskRequest(BaseModel):
    reason: str = Field(default="user_requested", max_length=200)


@background_tasks_router.post("/{task_id}/cancel")
async def cancel_background_task(
    task_id: str,
    body: Optional[CancelBackgroundTaskRequest] = None,
) -> dict[str, Any]:
    """Request cancellation of a running or pending task."""
    manager = _get_manager()
    reason = (body.reason if body is not None else "user_requested") or "user_requested"
    cancelled = await manager.cancel(task_id, reason=reason)
    if not cancelled:
        # Verify the row exists before returning 409; unknown -> 404.
        task = await manager.store.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Background task not found: {task_id}",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Background task not cancellable in status: {task.status.value}",
        )
    task = await manager.store.get_task(task_id)
    return {"task": _serialize_task(task) if task is not None else None}


@background_tasks_router.post("/{task_id}/retry")
async def retry_background_task(task_id: str) -> dict[str, Any]:
    """Re-queue a failed or cancelled task as a new attempt."""
    manager = _get_manager()
    task = await manager.retry(task_id)
    if task is None:
        existing = await manager.store.get_task(task_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Background task not found: {task_id}",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Background task not retriable in status: {existing.status.value}",
        )
    return {"task": _serialize_task(task)}


@background_tasks_router.post("/{task_id}/dismiss")
async def dismiss_background_task(task_id: str) -> dict[str, Any]:
    """Soft-delete a terminal task row.

    Only terminal rows can be dismissed; this is a user-driven list
    cleanup action and is not reversible.
    """
    manager = _get_manager()
    existing = await manager.store.get_task(task_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Background task not found: {task_id}",
        )
    terminal = {
        BackgroundTaskStatus.SUCCEEDED,
        BackgroundTaskStatus.FAILED,
        BackgroundTaskStatus.CANCELLED,
    }
    if existing.status not in terminal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Background task not dismissable in status: {existing.status.value}",
        )
    deleted = await manager.store.delete_task(task_id)
    return {"deleted": bool(deleted), "task_id": task_id}


__all__ = ["background_tasks_router"]
