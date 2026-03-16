"""L9 Sensors And Actions Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from ..core.runtime import SensorHub
from ..core.runtime.action_scheduler_contrib import ActionSchedulerContrib
from ..core.runtime.action_executor import ActionExecutor
from ..plugins import get_action_registry

logger = get_logger(__name__)


class SensorExecutorModule(LifecycleModule):
    """Initialize SensorHub and ActionExecutor (L9 - Sensors/Actuators layer)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_sensor_executor",
            dependencies=("runtime_message_bus",),
        )
        self._context = context

    async def init(self) -> None:
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")

        self._context.agent_runtime.sensor_hub = SensorHub(message_bus=message_bus)
        self._context.agent_runtime.action_executor = ActionExecutor(message_bus=message_bus)
        logger.info("SensorHub and ActionExecutor initialized (L9)")

    async def shutdown(self) -> None:
        self._context.agent_runtime.sensor_hub = None
        self._context.agent_runtime.action_executor = None


class ActionScheduleRegistrationModule(LifecycleModule):
    """Register action-owned scheduled handlers after scheduler startup."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_action_scheduler",
            dependencies=("runtime_sensor_executor", "runtime_scheduler"),
        )
        self._context = context
        self._contrib: ActionSchedulerContrib | None = None

    async def init(self) -> None:
        scheduler_service = require_initialized(self._context.scheduler.scheduler_service, "scheduler service")
        action_executor = require_initialized(self._context.agent_runtime.action_executor, "action executor")
        self._contrib = ActionSchedulerContrib(
            scheduler_service=scheduler_service,
            action_registry=get_action_registry(),
            action_executor=action_executor,
        )
        await self._contrib.register_schedules(scheduler_service)
        logger.info("Action schedule registration initialized (L9)")

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None
