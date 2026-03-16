"""Runtime bootstrap helpers for scheduler-backed targets.

Note: Handler registration has been migrated to layer-specific ScheduleContributor
implementations in production:
- AGENT_TASK -> AgentSchedulerContrib (agent/scheduler_contrib.py)
- ACTION_DISPATCH -> ActionSchedulerContrib (core/runtime/action_scheduler_contrib.py)

This class is retained for backward compatibility and testing scenarios.
"""
from __future__ import annotations

from functools import partial
from typing import Any

from ..plugins.actions import ActionRegistry
from ..utils.runtime import RuntimePaths
from .contracts import ScheduledTargetType
from .handlers import handle_action_dispatch, handle_agent_task
from .service import SchedulerService


class SchedulerBootstrap:
    """Legacy bootstrap class for scheduler handler registration.

    In production, handlers are registered via ScheduleContributor implementations.
    This class provides a convenience interface for testing and legacy code.
    """

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
        """Register AGENT_TASK and ACTION_DISPATCH handlers.

        Note: In production runtime, these handlers are registered via
        AgentSchedulerContrib and ActionSchedulerContrib. This method
        is provided for testing and backward compatibility.
        """
        self._scheduler_service.register_handler(
            ScheduledTargetType.AGENT_TASK,
            partial(handle_agent_task, self._task_agent_manager),
        )
        self._scheduler_service.register_handler(
            ScheduledTargetType.ACTION_DISPATCH,
            partial(handle_action_dispatch, self._action_registry, self._action_executor),
        )

