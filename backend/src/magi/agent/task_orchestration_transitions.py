"""Shared state transitions for task orchestration."""

from __future__ import annotations

import time

from .orchestration import TaskOrchestrationState


def mark_remaining_subtasks_cancelled(state: TaskOrchestrationState) -> None:
    now = time.time()
    for subtask in state.subtasks:
        if subtask.status in {"completed", "failed", "cancelled"}:
            continue
        subtask.status = "cancelled"
        subtask.updated_at = now


def is_terminal_state(state: TaskOrchestrationState) -> bool:
    return bool(state.subtasks) and all(
        item.status in {"completed", "failed", "cancelled"} for item in state.subtasks
    )
