"""Lifecycle module for dedicated chat persistence."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from .channel_attachments import ChatChannelAttachmentStore
from .channel_sessions import ChatChannelSessionProvisioner
from .conversation_log import ChatRunConsumedEventsStore, ConversationLog
from .projector import ChatProjector
from .store import ChatStore
from .user_turn_delivery import (
    ChatUserTurnDeliveryRecoveryService,
    ChatUserTurnDeliveryScheduler,
)
from .workspace_identity import claim_existing_session_workspaces

logger = get_logger(__name__)
_DELIVERY_RETRY_INTERVAL_SECONDS = 5.0


async def _reconcile_completed_chat_forget_barriers(
    *,
    memory,
    chat_read_service,
) -> dict[str, int]:
    """Rebuild chat-side barriers from the durable memory deletion ledger."""

    stats = {"operations": 0, "sessions": 0, "messages": 0}
    after_created_at: float | None = None
    after_operation_id: str | None = None
    while True:
        operations = await memory.list_completed_chat_forget_operations(
            limit=1000,
            after_created_at=after_created_at,
            after_operation_id=after_operation_id,
        )
        if not operations:
            return stats
        session_ids: list[str] = []
        message_scopes: list[tuple[str, str]] = []
        for operation in operations:
            payload = operation.selector.payload
            session_id = str(payload.get("session_id") or "").strip()
            if not session_id:
                continue
            if operation.selector.kind == "chat_session":
                session_ids.append(session_id)
            elif operation.selector.kind == "chat_message":
                message_scopes.append(
                    (session_id, str(payload.get("message_id") or ""))
                )
            elif operation.selector.kind == "chat_history":
                message_scopes.extend(
                    (session_id, str(message_id or ""))
                    for message_id in payload.get("surface_message_ids", [])
                )
        reconciled = await chat_read_service.abackfill_cleared_chat_scopes(
            session_ids,
            message_scopes,
        )
        stats["operations"] += len(operations)
        stats["sessions"] += int(reconciled["sessions"])
        stats["messages"] += int(reconciled["messages"])
        last = operations[-1]
        after_created_at = last.created_at
        after_operation_id = last.operation_id


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
        store = ChatStore(
            db_path=chat_db_path,
            runtime_paths=runtime_paths,
        )
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


class ChatAssistantMemoryProjectionModule(LifecycleModule):
    """Recover durable assistant-message projections until L1 confirms them."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_chat_assistant_memory_projection",
            dependencies=(
                "runtime_chat_store",
                "runtime_chat_projector",
                "runtime_command_queue",
                "runtime_memory",
                "runtime_memory_ingestion_subscriber",
                "runtime_chat_forgetting_recovery",
            ),
        )
        self._context = context

    async def init(self) -> None:
        from .assistant_memory_projection import (
            ChatAssistantMemoryProjectionService,
        )

        chat_store = require_initialized(self._context.chat.store, "chat store")
        chat_projector = require_initialized(
            self._context.chat.projector,
            "chat projector",
        )
        memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        runtime_command_queue = require_initialized(
            self._context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        )
        from .memory_projection_clear import ChatMemoryProjectionClearLifecycle

        clear_lifecycle = ChatMemoryProjectionClearLifecycle(
            read_current_clear_generation=(runtime_command_queue.read_current_clear_generation),
        )
        service = ChatAssistantMemoryProjectionService(
            outbox=chat_store,
            projector=chat_projector,
            unified_memory=memory,
            clear_lifecycle=clear_lifecycle,
        )
        self._context.chat.memory_projection_clear_lifecycle = clear_lifecycle
        self._context.chat.assistant_memory_projection_service = service
        chat_store.set_assistant_memory_outbox_waker(service.wake)
        await service.start()
        logger.info("Assistant-memory projection recovery started")

    async def shutdown(self) -> None:
        chat_store = self._context.chat.store
        if chat_store is not None:
            chat_store.set_assistant_memory_outbox_waker(None)
        service = self._context.chat.assistant_memory_projection_service
        self._context.chat.assistant_memory_projection_service = None
        if service is not None:
            await service.stop()
        self._context.chat.memory_projection_clear_lifecycle = None


class ChatForgettingRecoveryModule(LifecycleModule):
    """Finish chat-surface cleanup before any message processor starts."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_chat_forgetting_recovery",
            dependencies=(
                "runtime_chat_store",
                "runtime_memory",
                "runtime_command_queue",
            ),
        )
        self._context = context

    async def init(self) -> None:
        from .forgetting import ChatForgettingRecoveryService
        from .read_service import get_chat_read_service
        from .runtime_forgetting import ChatRuntimeForgettingCoordinator

        chat_read_service = get_chat_read_service()
        memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        reconciled = await _reconcile_completed_chat_forget_barriers(
            memory=memory,
            chat_read_service=chat_read_service,
        )
        global_clear_recovered = (
            await chat_read_service.arecover_interrupted_global_clear()
        )
        if global_clear_recovered:
            from ..memory.legacy_user_content import clear_legacy_user_content
            from .portrait.cache import clear_persisted_portrait_cache

            runtime_paths = require_initialized(
                self._context.core.runtime_paths,
                "runtime paths",
            )
            clear_persisted_portrait_cache(
                runtime_paths.cache_dir / "portrait" / "cache.json"
            )
            clear_legacy_user_content(runtime_paths)
        chat_store = require_initialized(self._context.chat.store, "chat store")
        runtime_command_queue = require_initialized(
            self._context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        )
        runtime = ChatRuntimeForgettingCoordinator(
            runtime_command_queue=runtime_command_queue,
            task_agent_manager=None,
            sensor_hub=None,
            chat_read_service=chat_read_service,
            delivery_scheduler=ChatUserTurnDeliveryScheduler(
                chat_store=chat_store,
                runtime_command_queue=runtime_command_queue,
            ),
            l0_store=memory.l0,
        )
        recovery = await ChatForgettingRecoveryService(
            chat_read_service=chat_read_service,
            memory=memory,
            runtime=runtime,
            assistant_memory_outbox=chat_store,
        ).recover_pending()
        if recovery["intents_found"] or recovery["surfaces_found"]:
            logger.info(
                "Recovered interrupted chat deletions",
                **recovery,
            )
        if global_clear_recovered:
            logger.info("Recovered interrupted global chat clear")
        if reconciled["sessions"] or reconciled["messages"]:
            logger.info(
                "Restored durable chat deletion barriers",
                **reconciled,
            )


class ChatDeliveryRecoveryModule(LifecycleModule):
    """Recover unfinished accepted user turns before command processing."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_chat_delivery_recovery",
            dependencies=(
                "runtime_chat_store",
                "runtime_chat_projector",
                "runtime_command_queue",
                "runtime_agent_core",
                "runtime_memory_ingestion_subscriber",
                "runtime_chat_assistant_memory_projection",
            ),
        )
        self._context = context
        self._recovery: ChatUserTurnDeliveryRecoveryService | None = None
        self._retry_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def init(self) -> None:
        from .read_service import get_chat_read_service

        chat_store = require_initialized(self._context.chat.store, "chat store")
        chat_projector = require_initialized(
            self._context.chat.projector,
            "chat projector",
        )
        runtime_command_queue = require_initialized(
            self._context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        )
        clear_lifecycle = require_initialized(
            self._context.chat.memory_projection_clear_lifecycle,
            "chat memory projection clear lifecycle",
        )
        scheduler = ChatUserTurnDeliveryScheduler(
            chat_store=chat_store,
            runtime_command_queue=runtime_command_queue,
        )
        recovery = ChatUserTurnDeliveryRecoveryService(
            chat_store=chat_store,
            chat_read_service=get_chat_read_service(),
            chat_projector=chat_projector,
            delivery_scheduler=scheduler,
            clear_lifecycle=clear_lifecycle,
        )
        stats = await recovery.recover_startup()
        self._context.chat.delivery_scheduler = scheduler
        self._recovery = recovery
        self._stop_event.clear()
        self._retry_task = asyncio.create_task(
            self._retry_loop(),
            name="chat-user-turn-delivery-recovery",
        )
        if stats.found:
            logger.info(
                "Recovered interrupted chat user-turn deliveries",
                **stats.as_dict(),
            )

    async def shutdown(self) -> None:
        self._stop_event.set()
        if self._retry_task is not None:
            self._retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._retry_task
            self._retry_task = None
        self._recovery = None
        self._context.chat.delivery_scheduler = None

    async def _retry_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=_DELIVERY_RETRY_INTERVAL_SECONDS,
                )
                continue
            except asyncio.TimeoutError:
                pass
            recovery = self._recovery
            if recovery is None:
                return
            try:
                stats = await recovery.retry_ready()
                if stats.found:
                    logger.info(
                        "Retried ready chat user-turn deliveries",
                        **stats.as_dict(),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Chat user-turn delivery retry failed")


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
            dependencies=(
                "runtime_chat_store",
                "runtime_message_bus",
                "runtime_memory",
                "runtime_control_plane",
            ),
        )
        self._context = context
        self._subscriber = None
        self._clear_coordinator = None

    async def init(self) -> None:
        from .control_transcript_subscriber import ControlTranscriptSubscriber

        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        control_module = require_initialized(
            self._context.control_plane.module,
            "control plane module",
        )
        wiring = require_initialized(control_module.wiring, "control plane wiring")
        self._clear_coordinator = wiring.user_content_clear
        self._subscriber = ControlTranscriptSubscriber(
            event_bus=message_bus,
            memory_epoch_getter=memory.memory_operation_epoch,
        )
        await self._subscriber.start()
        self._clear_coordinator.bind_transcript_subscriber(self._subscriber)
        logger.info("ControlTranscriptSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            if (
                self._clear_coordinator is not None
                and self._clear_coordinator.transcript_subscriber is self._subscriber
            ):
                self._clear_coordinator.bind_transcript_subscriber(None)
            await self._subscriber.stop()
            self._subscriber = None
        self._clear_coordinator = None
