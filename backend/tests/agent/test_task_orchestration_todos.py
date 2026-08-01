from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from magi.agent.orchestration import SubtaskDefinition, TaskOrchestrationState
from magi.agent.task_orchestration_todos import TaskOrchestrationTodosMixin


class _RecordingTodoStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, Any]]]] = []

    async def replace_todos(self, session_id: str, items: list[dict[str, Any]]):
        self.calls.append((session_id, list(items)))
        return []

    @asynccontextmanager
    async def user_content_operation(self):
        yield


class _TodoProjector(TaskOrchestrationTodosMixin):
    def __init__(self, store: _RecordingTodoStore) -> None:
        self._store = store
        self._control_session_store_provider = lambda: store


def _state_with_subtasks(statuses: list[str]) -> TaskOrchestrationState:
    return TaskOrchestrationState(
        orchestration_id="orch_1",
        user_id="u1",
        session_id="s1",
        root_user_message="organize files",
        turn_id="t1",
        planner="task_agent",
        workspace_root="/tmp",
        status="running",
        subtasks=[
            SubtaskDefinition(
                subtask_id=f"subtask_{index}",
                description=f"step {index}",
                subagent_type="CodeExplore",
                prompt="do it",
                status=status,
            )
            for index, status in enumerate(statuses, start=1)
        ],
    )


@pytest.mark.asyncio
async def test_publish_session_todos_clears_when_all_subtasks_terminal() -> None:
    store = _RecordingTodoStore()
    projector = _TodoProjector(store)
    state = _state_with_subtasks(["completed", "failed"])

    await projector._publish_session_todos(state)

    assert store.calls == [("s1", [])]


@pytest.mark.asyncio
async def test_publish_session_todos_keeps_single_in_progress_item() -> None:
    store = _RecordingTodoStore()
    projector = _TodoProjector(store)
    state = _state_with_subtasks(["running", "running", "pending"])

    await projector._publish_session_todos(state)

    statuses = [item["status"] for item in store.calls[-1][1]]

    assert statuses == ["in_progress", "not_started", "not_started"]
