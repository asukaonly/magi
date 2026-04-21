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
from .launch import (
    BackgroundLaunchService,
    build_background_run_fn,
    build_spec_from_request,
    default_ack_text,
)
from .manager import (
    BackgroundTaskListener,
    BackgroundTaskManager,
    TERMINAL_BACKGROUND_TASK_STATUSES,
)
from .memory_isolation import (
    BACKGROUND_SCOPE_KEY,
    BackgroundFactEmitter,
    BackgroundMemoryScope,
    get_background_scope,
    is_background_fact,
    tag_fact,
)
from .retention import BackgroundTaskRetentionGC
from .store import BackgroundTaskStore

__all__ = [
    "BACKGROUND_SCOPE_KEY",
    "BackgroundDecision",
    "BackgroundDecisionContext",
    "BackgroundDecisionSource",
    "BackgroundDisposition",
    "BackgroundDispatcher",
    "BackgroundFactEmitter",
    "BackgroundLaunchService",
    "BackgroundMemoryScope",
    "BackgroundRuleOutcome",
    "BackgroundTask",
    "BackgroundTaskEvent",
    "BackgroundTaskExecutor",
    "BackgroundTaskListener",
    "BackgroundTaskManager",
    "BackgroundTaskRetentionGC",
    "BackgroundTaskRunFn",
    "BackgroundTaskRunResult",
    "BackgroundTaskSpec",
    "BackgroundTaskStatus",
    "BackgroundTaskStore",
    "BackgroundTaskTriggerSource",
    "TERMINAL_BACKGROUND_TASK_STATUSES",
    "build_background_run_fn",
    "build_spec_from_request",
    "default_ack_text",
    "get_background_scope",
    "is_background_fact",
    "tag_fact",
]
