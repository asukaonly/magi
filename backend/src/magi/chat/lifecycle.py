"""Lifecycle module for dedicated chat persistence."""

from __future__ import annotations

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from .conversation_log import ChatRunConsumedEventsStore, ConversationLog
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
        # Phase F: lifecycle-owned conversation log + its consumed-events
        # store. Initialized in ``init()`` so resolvers in ChatTaskAgent
        # can pull the live instance off the module via the runtime
        # bootstrap context.
        self._consumed_events_store: ChatRunConsumedEventsStore | None = None
        self._conversation_log: ConversationLog | None = None

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        chat_db_path = str(runtime_paths.chat_db_path)
        store = ChatStore(db_path=chat_db_path)
        await store.initialize()
        self._context.chat.store = store
        # Phase F: build the ConversationLog alongside the ChatStore so
        # downstream consumers (ChatTaskAgent → ChatHistoryService) can
        # reach it through ``ctx.chat.module._conversation_log``. The
        # consumed-events store shares the chat DB file because the
        # chat-domain Alembic migration owns the
        # ``chat_run_consumed_events`` table.
        self._consumed_events_store = ChatRunConsumedEventsStore(db_path=chat_db_path)
        await self._consumed_events_store.initialize()
        self._conversation_log = ConversationLog(
            messages_repo=store,
            consumed_events_store=self._consumed_events_store,
        )
        self._context.chat.module = self
        logger.info("Chat store started")

    async def shutdown(self) -> None:
        if self._context.chat.store is not None:
            await self._context.chat.store.shutdown()
            self._context.chat.store = None
        self._conversation_log = None
        self._consumed_events_store = None
        self._context.chat.module = None


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
