"""L4 Plugin Registration Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext
from ..core.logger import get_logger
from . import get_sensor_registry, initialize_plugin_manager

logger = get_logger(__name__)


class PluginSystemModule(LifecycleModule):
    """Initialize plugin manager and plugin metadata (L4)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_plugin_system",
            dependencies=("runtime_message_bus",),
        )
        self._context = context

    async def init(self) -> None:
        self._context.plugins.plugin_manager = initialize_plugin_manager(force=True)
        self._context.plugins.sensor_registry = get_sensor_registry()

    async def shutdown(self) -> None:
        self._context.plugins.plugin_manager = None
        self._context.plugins.sensor_registry = None
