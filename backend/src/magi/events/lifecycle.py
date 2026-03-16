"""L3 Message Bus lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .sqlite_backend import SQLiteMessageBackend

logger = get_logger(__name__)


class MessageBusModule(LifecycleModule):
    """Start and stop message bus infrastructure (L3)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_message_bus",
            dependencies=("runtime_configuration", "runtime_core_dependencies"),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        self._context.message_bus.message_bus = SQLiteMessageBackend(
            db_path=str(runtime_paths.message_queue_db_path),
            max_queue_size=config.agent.message_bus.max_queue_size,
            num_workers=config.agent.message_bus.num_workers,
            broadcast_max_concurrency=config.agent.message_bus.broadcast_max_concurrency,
            handler_timeout_seconds=config.agent.message_bus.handler_timeout_seconds,
            max_retries=config.agent.message_bus.max_retries,
            retry_delay_seconds=config.agent.message_bus.retry_delay_seconds,
        )
        await self._context.message_bus.message_bus.start()
        logger.info("MessageBus started")

    async def shutdown(self) -> None:
        if self._context.message_bus.message_bus is not None:
            await self._context.message_bus.message_bus.stop()
            self._context.message_bus.message_bus = None
