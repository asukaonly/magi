"""
Task layer for five-layer architecture.
"""
from __future__ import annotations

import uuid
from typing import Optional

from ...core.task_database import TaskDatabase, TaskType, TaskPriority
from .contracts import LayerContext, RouteDecision, TaskEnvelope
from .types import LayerTaskType


class TaskLayer:
    """Creates task envelopes and optional persisted task records."""

    def __init__(self, task_database: Optional[TaskDatabase]) -> None:
        self._task_database = task_database

    async def build_task(self, context: LayerContext, decision: RouteDecision) -> TaskEnvelope:
        task_id = str(uuid.uuid4())
        payload = {
            "message": context.message,
            "user_id": context.user_id,
            "session_id": context.session_id,
            "intent": decision.intent,
        }

        if self._task_database:
            task_type = self._map_task_type(decision.task_type)
            db_task = await self._task_database.create_task(
                task_type=task_type,
                priority=TaskPriority.NORMAL,
                data=payload,
                timeout=120.0,
            )
            task_id = db_task.task_id

        return TaskEnvelope(
            task_id=task_id,
            context=context,
            decision=decision,
            payload=payload,
        )

    def _map_task_type(self, task_type: LayerTaskType) -> TaskType:
        mapping = {
            LayerTaskType.CHAT: TaskType.QUERY,
            LayerTaskType.INTERACTIVE: TaskType.INTERACTIVE,
            LayerTaskType.COMPUTATION: TaskType.COMPUTATION,
            LayerTaskType.BATCH: TaskType.BATCH,
            LayerTaskType.STUB_CAPABILITY: TaskType.INTERACTIVE,
        }
        return mapping.get(task_type, TaskType.QUERY)
