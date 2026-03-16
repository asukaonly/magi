"""Action layer scheduler contributor for ACTION_DISPATCH scheduled execution."""

from __future__ import annotations

from functools import partial
from typing import Any

from ..plugins.actions import ActionRegistry
from ..scheduler.contracts import ScheduledTargetType
from ..scheduler.handlers import handle_action_dispatch


class ActionSchedulerContrib:
    """Register the action layer's ACTION_DISPATCH handler with the scheduler."""

    def __init__(
        self,
        *,
        scheduler_service: Any,
        action_registry: ActionRegistry,
        action_emitter: Any,
    ) -> None:
        self._scheduler_service = scheduler_service
        self._action_registry = action_registry
        self._action_emitter = action_emitter

    async def register_schedules(self, scheduler: Any) -> None:
        scheduler.register_handler(
            ScheduledTargetType.ACTION_DISPATCH,
            partial(handle_action_dispatch, self._action_registry, self._action_emitter),
        )

    async def unregister_schedules(self, scheduler: Any) -> None:
        _ = scheduler
        return