"""L9 Sensors And Actions Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from ..core.runtime import SensorHub
from ..core.runtime.action_executor import ActionExecutor

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
