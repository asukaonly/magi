"""Lifecycle module for dedicated chat persistence."""

from __future__ import annotations

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from .projector import ChatProjector
from .store import ChatStore

logger = get_logger(__name__)


class ChatStoreModule(LifecycleModule):
    """Initialize and expose the dedicated chat store."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_chat_store",
            dependencies=("runtime_configuration", "runtime_core_dependencies"),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        store = ChatStore(db_path=str(runtime_paths.chat_db_path))
        await store.initialize()
        self._context.chat.store = store
        logger.info("Chat store started")

    async def shutdown(self) -> None:
        if self._context.chat.store is not None:
            await self._context.chat.store.shutdown()
            self._context.chat.store = None


class ChatProjectorModule(LifecycleModule):
    """Initialize the chat-to-memory projector."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_chat_projector",
            dependencies=("runtime_chat_store", "runtime_message_bus"),
        )
        self._context = context

    async def init(self) -> None:
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        self._context.chat.projector = ChatProjector(event_bus=message_bus)
        logger.info("Chat projector started")

    async def shutdown(self) -> None:
        self._context.chat.projector = None
