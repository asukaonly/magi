"""Background task runtime: detached long-running work per chat session.

Phase 0 ships only the persistence layer (contracts + store). Runtime
components — manager, executor, dispatcher — land in subsequent phases; see
``docs/dev/background-task-design.md`` for the end-to-end plan.
"""
from __future__ import annotations

from .contracts import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskTriggerSource,
)
from .store import BackgroundTaskStore

__all__ = [
    "BackgroundTask",
    "BackgroundTaskEvent",
    "BackgroundTaskSpec",
    "BackgroundTaskStatus",
    "BackgroundTaskStore",
    "BackgroundTaskTriggerSource",
]
