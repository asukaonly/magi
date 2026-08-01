"""L4 Plugin Registration Layer lifecycle module."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .manager import build_plugin_runtime
from .user_content_clear import PluginUserContentClearCoordinator
from .user_content_clear_checkpoint import PluginUserContentClearCheckpointStore

logger = get_logger(__name__)


class PluginSystemModule(LifecycleModule):
    """Initialize plugin manager and plugin metadata (L4)."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        *,
        tool_registry: Any,
        request_sensor_schedule_refresh: Callable[[], None],
    ):
        super().__init__(
            name="runtime_plugin_system",
            dependencies=("runtime_configuration", "runtime_command_queue"),
        )
        self._context = context
        self._tool_registry = tool_registry
        self._request_sensor_schedule_refresh = request_sensor_schedule_refresh
        self._runtime_loop: asyncio.AbstractEventLoop | None = None

    async def init(self) -> None:
        runtime_loop = asyncio.get_running_loop()
        self._runtime_loop = runtime_loop

        def request_sensor_schedule_refresh() -> None:
            if self._runtime_loop is not runtime_loop or runtime_loop.is_closed():
                return
            try:
                runtime_loop.call_soon_threadsafe(
                    self._run_sensor_schedule_refresh,
                    runtime_loop,
                )
            except RuntimeError:
                # The loop can close between the state check and scheduling.
                return

        bindings = build_plugin_runtime(
            tool_registry=self._tool_registry,
            request_sensor_schedule_refresh=request_sensor_schedule_refresh,
        )
        self._context.plugins.plugin_manager = bindings.plugin_manager
        self._context.plugins.plugin_projection_service = bindings.plugin_projection_service
        self._context.plugins.sensor_registry = bindings.sensor_registry
        self._context.plugins.user_content_clear_coordinator = (
            PluginUserContentClearCoordinator(
                plugin_manager=bindings.plugin_manager,
                runtime_paths=require_initialized(
                    self._context.core.runtime_paths,
                    "runtime paths",
                ),
                get_sensor_sync_executor=lambda: (
                    self._context.agent_runtime.sensor_sync_executor
                ),
                checkpoint_store=PluginUserContentClearCheckpointStore(
                    require_initialized(
                        self._context.core.runtime_paths,
                        "runtime paths",
                    ).message_queue_db_path
                ),
                read_current_clear_generation=require_initialized(
                    self._context.runtime_commands.runtime_command_queue,
                    "runtime command queue",
                ).read_current_clear_generation,
            )
        )
        try:
            await (
                self._context.plugins.user_content_clear_coordinator
            ).require_no_pending_generation()
        except BaseException:
            logger.exception(
                "Interrupted full user-content clear blocks runtime startup"
            )
            raise

    def _run_sensor_schedule_refresh(
        self,
        runtime_loop: asyncio.AbstractEventLoop,
    ) -> None:
        if self._runtime_loop is not runtime_loop or runtime_loop.is_closed():
            return
        self._request_sensor_schedule_refresh()

    async def shutdown(self) -> None:
        self._runtime_loop = None
        self._context.plugins.user_content_clear_coordinator = None
        self._context.plugins.plugin_manager = None
        self._context.plugins.plugin_projection_service = None
        self._context.plugins.sensor_registry = None
