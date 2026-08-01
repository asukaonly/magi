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
    _TERMINAL_SUBTASK_STATUSES = {"completed", "failed", "cancelled"}
    _TERMINAL_ORCHESTRATION_STATUSES = {"completed", "failed", "cancelled"}

    async def _publish_session_todos(self, state: TaskOrchestrationState) -> None:
        session_id = str(getattr(state, "session_id", "") or "").strip()
        if not session_id or not state.subtasks:
            return
        store = _resolve_control_session_store(self._control_session_store_provider)
        if store is None:
            return

        items = _build_session_todo_items(
            state,
            status_map=self._SUBTASK_TO_TODO_STATUS,
            terminal_subtask_statuses=self._TERMINAL_SUBTASK_STATUSES,
            terminal_orchestration_statuses=self._TERMINAL_ORCHESTRATION_STATUSES,
        )
        try:
            async with store.user_content_operation():
                if not await _replace_session_todos(
                    store,
                    state,
                    session_id,
                    items,
                ):
                    return
                await _publish_todo_state_changed(state, session_id, items)
                await _publish_todo_updated_event(state, session_id, items)
        except Exception as exc:  # pragma: no cover - defensive clear boundary
            logger.debug(
                "planner_todos.operation_rejected",
                session_id=session_id,
                orchestration_id=state.orchestration_id,
                error=str(exc),
            )


def _resolve_control_session_store(provider: Any) -> Any | None:
    if provider is None:
        return None
    try:
        return provider()
    except Exception:
        return None


def _build_session_todo_items(
    state: TaskOrchestrationState,
    *,
    status_map: dict[str, str],
    terminal_subtask_statuses: set[str],
    terminal_orchestration_statuses: set[str],
) -> list[dict[str, Any]]:
    if _should_clear_todos(
        state,
        terminal_subtask_statuses=terminal_subtask_statuses,
        terminal_orchestration_statuses=terminal_orchestration_statuses,
    ):
        return []

    items: list[dict[str, Any]] = []
    running_seen = False
    for subtask in state.subtasks:
        mapped = status_map.get(subtask.status, "not_started")
        mapped, running_seen = _cap_in_progress_status(mapped, running_seen)
        title = (subtask.description or "").strip() or subtask.subtask_id
        items.append(
            {
                "id": subtask.subtask_id,
                "content": title,
                "status": mapped,
            }
        )
    return items


def _should_clear_todos(
    state: TaskOrchestrationState,
    *,
    terminal_subtask_statuses: set[str],
    terminal_orchestration_statuses: set[str],
) -> bool:
    if str(state.status or "").strip() in terminal_orchestration_statuses:
        return True
    return all(
        str(subtask.status or "").strip() in terminal_subtask_statuses for subtask in state.subtasks
    )


def _cap_in_progress_status(mapped: str, running_seen: bool) -> tuple[str, bool]:
    if mapped != "in_progress":
        return mapped, running_seen
    if running_seen:
        return "not_started", running_seen
    return mapped, True


async def _replace_session_todos(
    store: Any,
    state: TaskOrchestrationState,
    session_id: str,
    items: list[dict[str, Any]],
) -> bool:
    try:
        await store.replace_todos(session_id, items)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(
            "planner_todos.replace_failed",
            session_id=session_id,
            orchestration_id=state.orchestration_id,
            error=str(exc),
        )
        return False


async def _publish_todo_state_changed(
    state: TaskOrchestrationState,
    session_id: str,
    items: list[dict[str, Any]],
) -> None:
    try:
        from magi.control.common.events import publish_control_todo_state_changed

        await publish_control_todo_state_changed(
            session_id=session_id,
            user_id=state.user_id,
            turn_id=state.turn_id,
            items=items,
            orchestration_id=state.orchestration_id,
        )
    except Exception:  # pragma: no cover - defensive
        logger.debug("planner_todos.persist_failed", exc_info=True)


async def _publish_todo_updated_event(
    state: TaskOrchestrationState,
    session_id: str,
    items: list[dict[str, Any]],
) -> None:
    try:
        from magi.control.common.events import publish_control_event

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
