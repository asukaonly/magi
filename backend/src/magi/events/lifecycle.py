"""L3 Message Bus lifecycle module."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from magi_plugin_sdk.ingress import PluginIngressEventRecord
from .contracts import RuntimeCommandType
from .plugin_ingress import PluginIngressRegistry
from .events import (
    Event,
    EventLevel,
    EventTypes,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
)
from .in_memory_backend import InMemoryMessageBusBackend
from .runtime_queue import (
    FULL_CLEAR_SENSITIVE_COMMAND_TYPES,
    SQLiteRuntimeCommandQueue,
)

logger = get_logger(__name__)
_FULL_DATA_CLEAR_TRANSACTION_ENV = "MAGI_FULL_DATA_CLEAR_TRANSACTION_ID"


class MessageBusModule(LifecycleModule):
    """Start and stop message bus infrastructure (L3)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_message_bus",
            dependencies=(
                "runtime_configuration",
                "runtime_core_dependencies",
                "runtime_command_queue",
            ),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        self._context.message_bus.message_bus = InMemoryMessageBusBackend(
            max_queue_size=config.agent.message_bus.max_queue_size,
            num_workers=config.agent.message_bus.num_workers,
            broadcast_max_concurrency=config.agent.message_bus.broadcast_max_concurrency,
            handler_timeout_seconds=config.agent.message_bus.handler_timeout_seconds,
        )
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Message bus workers held for full-clear recovery")
        else:
            await self._context.message_bus.message_bus.start()
            logger.info("MessageBus started")

    async def shutdown(self) -> None:
        if self._context.message_bus.message_bus is not None:
            await self._context.message_bus.message_bus.stop()
            self._context.message_bus.message_bus = None


class RuntimeCommandQueueModule(LifecycleModule):
    """Start the persisted runtime command queue."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_command_queue",
            dependencies=("runtime_configuration", "runtime_core_dependencies"),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        queue = SQLiteRuntimeCommandQueue(db_path=str(runtime_paths.message_queue_db_path))
        await queue.start(recover_claimed_commands=False)
        owner_transaction_id = os.environ.get(
            _FULL_DATA_CLEAR_TRANSACTION_ENV,
            "",
        ).strip()
        if owner_transaction_id:
            await queue.begin_full_user_content_clear(owner_transaction_id)
        transaction_state = await queue.read_full_user_content_clear_state()
        recovery_pending = transaction_state.status == "pending"
        if recovery_pending and not owner_transaction_id:
            await queue.stop()
            raise RuntimeError("Pending full user-content clear requires its service owner marker")
        self._context.runtime_commands.full_clear_recovery_pending = recovery_pending
        if not recovery_pending:
            await queue.recover_claimed_commands_after_restart()
        self._context.runtime_commands.runtime_command_queue = queue
        logger.info(
            "Runtime command queue started",
            full_clear_recovery_pending=recovery_pending,
        )

    async def shutdown(self) -> None:
        queue = self._context.runtime_commands.runtime_command_queue
        if queue is not None:
            await queue.stop()
            self._context.runtime_commands.runtime_command_queue = None
        self._context.runtime_commands.full_clear_recovery_pending = False


class RuntimeCommandProcessorModule(LifecycleModule):
    """Consume persisted runtime commands and inject local integration events."""

    def __init__(self, context: RuntimeBootstrapContext, *, poll_interval_seconds: float = 0.1):
        super().__init__(
            name="runtime_command_processor",
            dependencies=(
                "runtime_command_queue",
                "runtime_agent_core",
                "runtime_exports",
                "runtime_message_bus",
                "runtime_chat_forgetting_recovery",
                "runtime_chat_assistant_memory_projection",
                "runtime_chat_delivery_recovery",
            ),
        )
        self._context = context
        self._poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False
        self._draining = False
        self._active_commands = 0
        self._idle_event = asyncio.Event()
        self._idle_event.set()

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            self._running = False
            self._draining = True
            self._context.runtime_commands.runtime_command_processor = self
            logger.warning("Runtime command processor held for full-clear recovery")
            return
        self._running = True
        self._draining = False
        self._active_commands = 0
        self._idle_event.set()
        self._context.runtime_commands.runtime_command_processor = self
        self._task = asyncio.create_task(self._run_loop())

    async def shutdown(self) -> None:
        self._running = False
        self._context.runtime_commands.runtime_command_processor = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def is_draining(self) -> bool:
        """Return whether the processor has stopped claiming new commands."""
        return self._draining

    def begin_draining(self) -> None:
        """Stop claiming new commands and wait for active work to finish."""
        self._draining = True
        if self._active_commands == 0:
            self._idle_event.set()

    async def wait_until_idle(self, timeout_seconds: float | None = None) -> None:
        """Wait until the processor has no in-flight commands."""
        if timeout_seconds is None:
            await self._idle_event.wait()
            return
        await asyncio.wait_for(self._idle_event.wait(), timeout=timeout_seconds)

    async def _run_loop(self) -> None:
        queue = require_initialized(
            self._context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        )
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")

        while self._running:
            try:
                await self._run_next_command(queue=queue, message_bus=message_bus)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Runtime command processing failed", error=str(exc))
                await asyncio.sleep(self._poll_interval_seconds)

    async def _run_next_command(self, *, queue: Any, message_bus: Any) -> None:
        if self._draining:
            await asyncio.sleep(self._poll_interval_seconds)
            return

        command = None
        async with queue.clear_sensitive_command_operation():
            if not self._draining:
                command = await self._claim_next_command(queue)
            if command is not None:
                await self._process_claimed_command(
                    queue=queue,
                    command=command,
                    message_bus=message_bus,
                )

        if command is None:
            await asyncio.sleep(self._poll_interval_seconds)

    async def _process_claimed_command(
        self,
        *,
        queue: Any,
        command: Any,
        message_bus: Any,
    ) -> None:
        """Execute one claimed command while its clear boundary remains shared."""

        self._mark_command_started()
        try:
            if command.command_type is RuntimeCommandType.USER_MESSAGE:
                async with queue.user_message_operation():
                    if await queue.is_user_message_command_blocked(command):
                        logger.info(
                            "Discarding user-message runtime command for a deleted chat scope",
                            command_id=command.command_id,
                            session_id=str(command.payload.get("session_id") or ""),
                            turn_id=str(command.payload.get("turn_id") or ""),
                        )
                        await queue.ack(command.command_id)
                        return
                    await self._execute_admitted_command(
                        queue=queue,
                        command=command,
                        message_bus=message_bus,
                    )
                return
            await self._execute_admitted_command(
                queue=queue,
                command=command,
                message_bus=message_bus,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                queue.requeue(
                    command.command_id,
                    error_text="RUNTIME_COMMAND_PROCESSOR_CANCELLED",
                )
            )
            raise
        except BaseException as exc:
            await asyncio.shield(
                queue.requeue(
                    command.command_id,
                    error_text=f"RUNTIME_COMMAND_HANDLER_FAILED:{type(exc).__name__}",
                )
            )
            raise
        finally:
            self._mark_command_finished()

    async def _execute_admitted_command(
        self,
        *,
        queue: Any,
        command: Any,
        message_bus: Any,
    ) -> None:
        if (
            command.command_type in FULL_CLEAR_SENSITIVE_COMMAND_TYPES
            and int(command.user_message_generation) != queue.current_user_message_generation()
        ):
            logger.info(
                "Discarding stale clear-sensitive runtime command",
                command_id=command.command_id,
                command_type=command.command_type.value,
                command_generation=command.user_message_generation,
                current_generation=queue.current_user_message_generation(),
            )
            await queue.ack(command.command_id)
            return
        published = await self._execute_runtime_command(command, message_bus)
        await self._complete_runtime_command(queue, command, published)

    async def _claim_next_command(self, queue: Any) -> Any | None:
        return await queue.claim_next(
            consumer_name="runtime_worker",
            command_types=(
                RuntimeCommandType.USER_MESSAGE,
                RuntimeCommandType.REFRESH_LLM_CONFIG,
                RuntimeCommandType.REFRESH_CHANNELS,
                RuntimeCommandType.SOURCE_SYNC,
                RuntimeCommandType.SOURCE_STATE_FLUSH,
            ),
        )

    def _mark_command_started(self) -> None:
        self._active_commands += 1
        self._idle_event.clear()

    def _mark_command_finished(self) -> None:
        self._active_commands = max(0, self._active_commands - 1)
        if self._active_commands == 0:
            self._idle_event.set()

    async def _execute_runtime_command(self, command: Any, message_bus: Any) -> bool:
        if command.command_type is RuntimeCommandType.USER_MESSAGE:
            return await self._publish_user_message_command(command, message_bus)
        if command.command_type is RuntimeCommandType.REFRESH_LLM_CONFIG:
            self._refresh_runtime_llm_config()
            return True
        if command.command_type is RuntimeCommandType.REFRESH_CHANNELS:
            await self._refresh_channels()
            return True
        if command.command_type is RuntimeCommandType.SOURCE_SYNC:
            await self._queue_source_sync(command)
            return True
        if command.command_type is RuntimeCommandType.SOURCE_STATE_FLUSH:
            await self._flush_source_state(command)
            return True
        raise RuntimeError(f"Unsupported runtime command type: {command.command_type}")

    async def _complete_runtime_command(self, queue: Any, command: Any, published: bool) -> None:
        if published:
            if command.command_type is RuntimeCommandType.USER_MESSAGE:
                return
            await queue.ack(command.command_id)
        else:
            await queue.requeue(
                command.command_id,
                error_text="LOCAL_MESSAGE_BUS_PUBLISH_FAILED",
            )

    async def _publish_user_message_command(self, command: Any, message_bus: Any) -> bool:
        user_message = command.as_user_message()
        event_identity = (
            f"{user_message.correlation_id}:"
            f"{command.delivery_attempt_no}:"
            f"{command.runtime_command_id}"
        )
        event_digest = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"magi:runtime-user-message:{event_identity}",
        ).hex
        return await message_bus.publish(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "content": user_message.message,
                    "attachments": list(user_message.attachments),
                    "author_type": "user",
                    "content_type": "text",
                    "user_id": user_message.user_id,
                    "runtime_namespace": user_message.runtime_namespace,
                    "session_id": user_message.session_id,
                    "turn_id": user_message.turn_id,
                    "workspace_path": user_message.workspace_path,
                    "timestamp": float(user_message.created_at),
                    "metadata": dict(user_message.metadata),
                    "source": user_message.source,
                    "user_message_generation": int(command.user_message_generation),
                    "delivery_attempt_no": int(command.delivery_attempt_no),
                    "runtime_command_id": int(command.runtime_command_id),
                },
                source=user_message.source,
                level=EventLevel.INFO,
                correlation_id=user_message.correlation_id,
                event_id=(
                    "runtime-user-message:"
                    f"{command.delivery_attempt_no}:"
                    f"{command.runtime_command_id}:"
                    f"{event_digest}"
                ),
                metadata={REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY: True},
            )
        )

    @staticmethod
    def _refresh_runtime_llm_config() -> None:
        from ..bootstrap.backend import refresh_runtime_llm_config
        from ..config.loader import reload_config

        refreshed_config = reload_config()
        refresh_runtime_llm_config(refreshed_config)

    async def _refresh_channels(self) -> None:
        from ..config.loader import reload_config

        reload_config()
        channels_module = self._context.channels.module
        if channels_module is not None:
            await channels_module.restart()

    async def _queue_source_sync(self, command: Any) -> None:
        source_sync = command.as_source_sync()
        source_scheduler = require_initialized(
            self._context.agent_runtime.source_scheduler_contrib,
            "source scheduler contributor",
        )
        await source_scheduler.queue_manual_sync(
            source_sync.source_name,
            connection_id=source_sync.connection_id,
            first_context=source_sync.first_context,
            sync_mode=source_sync.sync_mode,
            backfill_scope=source_sync.backfill_scope,
            backfill_days=source_sync.backfill_days,
            backfill_start_date=source_sync.backfill_start_date,
            backfill_end_date=source_sync.backfill_end_date,
        )

    async def _flush_source_state(self, command: Any) -> None:
        source_flush = command.as_source_state_flush()
        source_sync_executor = require_initialized(
            self._context.agent_runtime.source_sync_executor,
            "source sync executor",
        )
        await source_sync_executor.flush_source_state(source_flush.source_name, connection_id=source_flush.connection_id)


class PluginIngressProcessorModule(LifecycleModule):
    """Consume persisted plugin ingress events and route them to handlers."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        *,
        global_clear_pending: Callable[[], Awaitable[bool]],
        registry: PluginIngressRegistry | None = None,
        connection_store=None,
        poll_interval_seconds: float = 0.1,
        concurrency: int = 4,
    ):
        super().__init__(
            name="runtime_plugin_ingress_processor",
            dependencies=("runtime_trace", "runtime_plugin_activation"),
        )
        self._context = context
        self._poll_interval_seconds = poll_interval_seconds
        self._concurrency = max(1, min(8, concurrency))
        self._task: asyncio.Task | None = None
        self._running = False
        from ..core.container import get_container

        self._delivery_registry = registry or get_container().plugin_ingress_registry()
        self._connection_store = connection_store
        self._global_clear_pending = global_clear_pending

    async def init(self) -> None:
        self._delivery_registry.ready = False
        if self._connection_store is None:
            manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
            self._connection_store = manager.connection_store
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Plugin ingress processor held for full-clear recovery")
            return
        if os.environ.get("MAGI_MEMORY_RESTORE_OPERATION_ID"):
            logger.info("Plugin ingress processor held for memory restore verification")
            return
        store = require_initialized(self._context.runtime_trace.store, "runtime trace store")
        try:
            data_epoch = str(uuid.UUID(os.environ.get("MAGI_DATA_EPOCH", "")))
        except ValueError as exc:
            raise RuntimeError("Service data epoch is missing or invalid") from exc
        await store.recover_background_delivery_claims(data_epoch=data_epoch)
        async with store.plugin_ingress_operation():
            for connection_id in await store.plugin_ingress_connection_ids():
                try:
                    epoch = self._connection_store.ingress_epoch(connection_id)
                except KeyError:
                    epoch = None
                await store.retire_connection_ingress(connection_id, keep_epoch=epoch)
        self._delivery_registry.ready = True
        self._running = True
        self._task = asyncio.create_task(self._run_consumers())

    async def _run_consumers(self) -> None:
        consumers = [asyncio.create_task(self._run_loop()) for _ in range(self._concurrency)]
        try:
            await asyncio.gather(*consumers)
        finally:
            for task in consumers:
                task.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)

    async def shutdown(self) -> None:
        self._running = False
        self._delivery_registry.ready = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        store = require_initialized(self._context.runtime_trace.store, "runtime trace store")

        while self._running:
            try:
                async with store.plugin_ingress_operation():
                    event = await store.claim_next_plugin_ingress_event(
                        consumer_name="runtime_worker"
                    )
                    if event is not None and await self._global_clear_pending():
                        await store.clear_plugin_ingress_events()
                        event = None
                    if event is not None:
                        await self._dispatch_event(store, event)
                if event is None:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Plugin ingress processing failed", error=str(exc))
                await asyncio.sleep(self._poll_interval_seconds)

    async def _dispatch_event(
        self,
        store,
        event: PluginIngressEventRecord,
    ) -> None:
        try:
            epoch = self._connection_store.ingress_epoch(event.connection_id)
        except KeyError:
            epoch = None
        if epoch != event.connection_epoch:
            await store.retire_connection_ingress(event.connection_id, keep_epoch=epoch)
            return
        with self._delivery_registry.lease(
            event.connection_id, event.connection_epoch, event.plugin_target, event.event_type
        ) as registration:
            if registration is None:
                if not self._delivery_registry.connection_active(event.connection_id):
                    await store.defer_plugin_ingress(event.event_id)
                else:
                    await store.fail_plugin_ingress_event(event.event_id, error_text="handler_unavailable")
                return
            if event.source_kind == "background_delivery" and not registration.replay_safe:
                await store.fail_plugin_ingress_event(event.event_id, error_text="handler_not_replay_safe")
                return
            try:
                payload = json.loads(event.payload_json or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("Plugin ingress payload must be an object")
                await asyncio.wait_for(registration.handler.handle_event(event, payload), timeout=60)
            except Exception as exc:
                if event.source_kind == "background_delivery":
                    from magi_plugin_sdk.ingress import IngressProcessingError, classify_ingress_error
                    code = classify_ingress_error(exc)
                    if code in IngressProcessingError.PERMANENT:
                        await store.fail_plugin_ingress_event(event.event_id, error_text=code)
                    else:
                        await store.retry_background_delivery(event.event_id, code=code)
                else:
                    await store.fail_plugin_ingress_event(event.event_id, error_text=str(exc))
                return
            await store.complete_plugin_ingress_event(event.event_id)
