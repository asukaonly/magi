"""Agent layer's scheduler contributor for AGENT_TASK scheduled execution."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..scheduler.contracts import ScheduledTargetType
from ..scheduler.handlers import handle_agent_task

if TYPE_CHECKING:
    from ..scheduler.contracts import ScheduleContributor
    from ..scheduler.service import SchedulerService


class AgentSchedulerContrib:
    """Agent layer's scheduler contributor.

    Implements ScheduleContributor protocol to register the AGENT_TASK
    handler with the unified scheduler.
    """

    def __init__(
        self,
        *,
        scheduler_service: SchedulerService,
        task_agent_manager: Any,
    ) -> None:
        self._scheduler_service = scheduler_service
        self._task_agent_manager = task_agent_manager

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        """Register agent task handler (ScheduleContributor protocol)."""
        from functools import partial

        scheduler.register_handler(
            ScheduledTargetType.AGENT_TASK,
            partial(handle_agent_task, self._task_agent_manager),
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        """Unregister agent task handler (ScheduleContributor protocol).

        Note: The scheduler service doesn't currently support unregistering
        handlers, so this is a no-op for now.
        """
        pass
