"""Action executor's scheduler contributor for ACTION_DISPATCH scheduled execution."""
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from ...plugins.actions import ActionRegistry
from ...scheduler.contracts import ScheduledTargetType
from ...scheduler.handlers import handle_action_dispatch

if TYPE_CHECKING:
    from ...scheduler.contracts import ScheduleContributor
    from ...scheduler.service import SchedulerService


class ActionSchedulerContrib:
    """Action executor's scheduler contributor.

    Implements ScheduleContributor protocol to register the ACTION_DISPATCH
    handler with the unified scheduler.
    """

    def __init__(
        self,
        *,
        scheduler_service: SchedulerService,
        action_registry: ActionRegistry,
        action_executor: Any,
    ) -> None:
        self._scheduler_service = scheduler_service
        self._action_registry = action_registry
        self._action_executor = action_executor

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        """Register action dispatch handler (ScheduleContributor protocol)."""
        scheduler.register_handler(
            ScheduledTargetType.ACTION_DISPATCH,
            partial(handle_action_dispatch, self._action_registry, self._action_executor),
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        """Unregister action dispatch handler (ScheduleContributor protocol).

        Note: The scheduler service doesn't currently support unregistering
        handlers, so this is a no-op for now.
        """
        pass
