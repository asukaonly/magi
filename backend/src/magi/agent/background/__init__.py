"""Background task runtime: detached long-running work per chat session.

Phases 0-2 ship the persistence layer (contracts + store), the lifecycle
executor, and the scheduling manager. Phase 3 will introduce the
dispatcher and wire in ``FunctionCallingOrchestrator`` as the concrete
run function. See ``docs/dev/background-task-design.md`` for the
end-to-end plan.
"""
from __future__ import annotations

from .contracts import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskTriggerSource,
)
from .dispatcher import (
    BackgroundDecision,
    BackgroundDecisionContext,
    BackgroundDecisionSource,
    BackgroundDisposition,
    BackgroundDispatcher,
    BackgroundRuleOutcome,
)
from .executor import (
    BackgroundTaskExecutor,
    BackgroundTaskRunFn,
    BackgroundTaskRunResult,
)
from .manager import BackgroundTaskManager
from .store import BackgroundTaskStore

__all__ = [
    "BackgroundDecision",
    "BackgroundDecisionContext",
    "BackgroundDecisionSource",
    "BackgroundDisposition",
    "BackgroundDispatcher",
    "BackgroundRuleOutcome",
    "BackgroundTask",
    "BackgroundTaskEvent",
    "BackgroundTaskExecutor",
    "BackgroundTaskManager",
    "BackgroundTaskRunFn",
    "BackgroundTaskRunResult",
    "BackgroundTaskSpec",
    "BackgroundTaskStatus",
    "BackgroundTaskStore",
    "BackgroundTaskTriggerSource",
]
