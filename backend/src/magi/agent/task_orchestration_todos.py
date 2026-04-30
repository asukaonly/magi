"""Planner-owned todo projection for task orchestration."""

from __future__ import annotations

from typing import Any

from ..core.logger import get_logger
from .orchestration import TaskOrchestrationState

logger = get_logger(__name__)


class TaskOrchestrationTodosMixin:
    """Mirror orchestration subtasks onto the control-plane todo list."""

    _control_session_store_provider: Any

    _SUBTASK_TO_TODO_STATUS = {
        "pending": "not_started",
        "running": "in_progress",
        "completed": "completed",
        "failed": "completed",
        "cancelled": "not_started",
    }

    async def _publish_session_todos(self, state: TaskOrchestrationState) -> None:
        """Mirror orchestration subtasks onto the session's todo list.

        The control-plane ``ControlSessionStore`` caps ``in_progress`` to
        one item. We honour that by keeping only the first running
        subtask as ``in_progress`` and demoting the rest to
        ``not_started`` for display purposes — their real status remains
        tracked on ``state.subtasks``.
        """
        session_id = str(getattr(state, "session_id", "") or "").strip()
        if not session_id or not state.subtasks:
            return
        if self._control_session_store_provider is None:
            return
        try:
            store = self._control_session_store_provider()
        except Exception:
            return

        items: list[dict[str, Any]] = []
        running_seen = False
        for subtask in state.subtasks:
            mapped = self._SUBTASK_TO_TODO_STATUS.get(subtask.status, "not_started")
            if mapped == "in_progress":
                if running_seen:
                    mapped = "not_started"
                else:
                    running_seen = True
            title = (subtask.description or "").strip() or subtask.subtask_id
            items.append(
                {
                    "id": subtask.subtask_id,
                    "content": title,
                    "status": mapped,
                }
            )

        try:
            await store.replace_todos(session_id, items)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "planner_todos.replace_failed",
                session_id=session_id,
                orchestration_id=state.orchestration_id,
                error=str(exc),
            )
            return

        try:
            from .control.chat_state_persister import persist_todo_state_message

            await persist_todo_state_message(
                session_id=session_id,
                user_id=state.user_id,
                turn_id=state.turn_id,
                items=items,
                orchestration_id=state.orchestration_id,
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("planner_todos.persist_failed", exc_info=True)

        try:
            from .control.common.events import publish_control_event

            await publish_control_event(
                "control.todo.updated",
                {
                    "session_id": session_id,
                    "orchestration_id": state.orchestration_id,
                    "items": items,
                },
                session_id=session_id,
                user_id=state.user_id,
                turn_id=state.turn_id,
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("planner_todos.event_failed", exc_info=True)