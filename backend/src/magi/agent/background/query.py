"""Bounded, owner-scoped read model for agent questions about background work."""

from __future__ import annotations

import time
from typing import Any

from .contracts import BackgroundTask, BackgroundTaskStatus
from .store import BackgroundTaskStore


class BackgroundTaskQueryService:
    """Read durable task facts without exposing run inputs or execution controls."""

    def __init__(self, store: BackgroundTaskStore) -> None:
        self._store = store

    async def query(
        self, *, user_id: str, session_id: str | None = None,
        task_id: str | None = None, status: str | None = None,
        limit: int = 10, offset: int = 0,
    ) -> dict[str, Any]:
        if not user_id.strip():
            raise ValueError("A task owner is required")
        if not 1 <= limit <= 20 or offset < 0:
            raise ValueError("Invalid task query pagination")
        statuses = [BackgroundTaskStatus(status)] if status else None
        if task_id:
            task = await self._store.get_task(task_id)
            if task is None or task.spec.user_id != user_id or (
                session_id is not None and task.spec.session_id != session_id
            ):
                raise LookupError("Task not found in the requested scope")
            tasks, has_more = [task], False
        else:
            rows = await self._store.list_tasks(
                user_id=user_id, session_id=session_id, statuses=statuses,
                limit=limit + 1, offset=offset,
            )
            tasks, has_more = rows[:limit], len(rows) > limit
        return {
            "tasks": [_task_snapshot(task) for task in tasks],
            "has_more": has_more,
            "next_offset": offset + limit if has_more else None,
            "observed_at": time.time(),
            "source": "background_task_store",
        }


def _task_snapshot(task: BackgroundTask) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "task_id": task.task_id,
        "session_id": task.spec.session_id,
        "origin_turn_id": task.spec.origin_turn_id,
        "status": task.status.value,
        "attempt_index": task.attempt_index,
        "requires_user_input": task.status == BackgroundTaskStatus.SUSPENDED_WAITING_USER,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }
    truncated: list[str] = []
    for key, value, budget in (
        ("title", task.spec.title, 200),
        ("goal", task.spec.goal, 1000),
        ("summary", task.summary, 2000),
        ("error", task.error, 1000),
        ("cancel_reason", task.cancel_reason, 500),
    ):
        snapshot[key] = value[:budget] if value is not None else None
        if value is not None and len(value) > budget:
            truncated.append(key)
    snapshot["truncated_fields"] = truncated
    return snapshot
