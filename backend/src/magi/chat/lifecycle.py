"""Lifecycle module for dedicated chat persistence."""

from __future__ import annotations

import asyncio

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from .channel_attachments import ChatChannelAttachmentStore
from .channel_sessions import ChatChannelSessionProvisioner
from .conversation_log import ChatRunConsumedEventsStore, ConversationLog
from .projector import ChatProjector
from .store import ChatStore
from .workspace_identity import claim_existing_session_workspaces

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
        # store. Initialized in ``init()`` so lifecycle assembly can pass
        # the live instance into chat runtime wiring.
        self._consumed_events_store: ChatRunConsumedEventsStore | None = None
        self._conversation_log: ConversationLog | None = None

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        chat_db_path = str(runtime_paths.chat_db_path)
        store = ChatStore(db_path=chat_db_path)
        await store.initialize()
        claimed_workspace_count = await asyncio.to_thread(
            claim_existing_session_workspaces,
            chat_db_path,
        )
        self._context.chat.store = store
        self._context.chat.channel_session_provisioner = ChatChannelSessionProvisioner(
            chat_store=store,
        )
        self._context.chat.channel_attachment_store = ChatChannelAttachmentStore(
            runtime_paths=runtime_paths,
        )
        # Phase F: build the ConversationLog alongside the ChatStore so
        # downstream consumers can reach it through lifecycle-injected
        # chat runtime wiring. The
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
        logger.info(
            "Chat store started",
            claimed_workspace_count=claimed_workspace_count,
        )

    async def shutdown(self) -> None:
        if self._context.chat.store is not None:
            await self._context.chat.store.shutdown()
            self._context.chat.store = None
        self._context.chat.channel_session_provisioner = None
        self._context.chat.channel_attachment_store = None
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


class ControlTranscriptSubscriberModule(LifecycleModule):
    """Wire the control->chat transcript subscriber to the runtime event bus.

    Control-Plane Extraction Phase 1: the control-actuator tools publish
    control state-change events on the L3 bus; this chat-side subscriber owns
    the durable transcript projection (formerly in
    ``magi.control.chat_state_persister``). Depends on the chat store so
    ``get_chat_store()`` resolves inside the projector, and on the message bus
    so it can subscribe.
    """

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_control_transcript_subscriber",
            dependencies=("runtime_chat_store", "runtime_message_bus"),
        )
        self._context = context
        self._subscriber = None

    async def init(self) -> None:
        from .control_transcript_subscriber import ControlTranscriptSubscriber

        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        self._subscriber = ControlTranscriptSubscriber(event_bus=message_bus)
        await self._subscriber.start()
        logger.info("ControlTranscriptSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None
