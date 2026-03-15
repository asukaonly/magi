"""Runtime bootstrap helpers for scheduler-backed targets."""
from __future__ import annotations

from functools import partial
from typing import Any

from ..plugins.actions import ActionRegistry
from ..utils.runtime import RuntimePaths
from .contracts import ScheduledTargetType
from .handlers import handle_action_dispatch, handle_agent_task
from .service import SchedulerService

# Re-export for backward compatibility — canonical location is timeline.scheduler_contrib
from ..timeline.scheduler_contrib import (  # noqa: F401
    build_timeline_schedule_id,
    build_timeline_target_key,
)


class SchedulerBootstrap:
    """Registers generic scheduled-execution handlers (agent tasks and action dispatch)."""

    def __init__(
        self,
        *,
        scheduler_service: SchedulerService,
        action_registry: ActionRegistry,
        runtime_paths: RuntimePaths,
        task_agent_manager: Any,
        action_executor: Any,
    ) -> None:
        self._scheduler_service = scheduler_service
        self._action_registry = action_registry
        self._runtime_paths = runtime_paths
        self._task_agent_manager = task_agent_manager
        self._action_executor = action_executor

    def register_handlers(self) -> None:
        self._scheduler_service.register_handler(
            ScheduledTargetType.AGENT_TASK,
            partial(handle_agent_task, self._task_agent_manager),
        )
        self._scheduler_service.register_handler(
            ScheduledTargetType.ACTION_DISPATCH,
            partial(handle_action_dispatch, self._action_registry, self._action_executor),
        )

