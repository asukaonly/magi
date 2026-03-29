"""L4 Plugin Registration Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext
from ..core.logger import get_logger
from .manager import build_plugin_runtime

logger = get_logger(__name__)


class PluginSystemModule(LifecycleModule):
    """Initialize plugin manager and plugin metadata (L4)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_plugin_system",
            dependencies=("runtime_configuration",),
        )
        self._context = context

    async def init(self) -> None:
        bindings = build_plugin_runtime()
        self._context.plugins.plugin_manager = bindings.plugin_manager
        self._context.plugins.sensor_registry = bindings.sensor_registry
        self._context.plugins.action_registry = bindings.action_registry

    async def shutdown(self) -> None:
        self._context.plugins.plugin_manager = None
        self._context.plugins.sensor_registry = None
        self._context.plugins.action_registry = None
