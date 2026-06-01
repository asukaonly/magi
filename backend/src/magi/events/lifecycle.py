"""L3 Message Bus lifecycle module."""

from __future__ import annotations

import asyncio
import json

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from magi_plugin_sdk.ingress import PluginIngressEventRecord
from .contracts import RuntimeCommandType
from .plugin_ingress import PluginIngressHandlerRegistration
from .events import (
    Event,
    EventLevel,
    EventTypes,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
)
from .in_memory_backend import InMemoryMessageBusBackend
from .runtime_queue import SQLiteRuntimeCommandQueue

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
        self._context.message_bus.message_bus = InMemoryMessageBusBackend(
            max_queue_size=config.agent.message_bus.max_queue_size,
            num_workers=config.agent.message_bus.num_workers,
            broadcast_max_concurrency=config.agent.message_bus.broadcast_max_concurrency,
            handler_timeout_seconds=config.agent.message_bus.handler_timeout_seconds,
        )
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
        await queue.start()
        self._context.runtime_commands.runtime_command_queue = queue
        logger.info("Runtime command queue started")

    async def shutdown(self) -> None:
        queue = self._context.runtime_commands.runtime_command_queue
        if queue is not None:
            await queue.stop()
            self._context.runtime_commands.runtime_command_queue = None


class RuntimeCommandProcessorModule(LifecycleModule):
    """Consume persisted runtime commands and inject local integration events."""

    def __init__(self, context: RuntimeBootstrapContext, *, poll_interval_seconds: float = 0.1):
        super().__init__(
            name="runtime_command_processor",
            dependencies=("runtime_command_queue", "runtime_agent_core", "runtime_message_bus"),
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
                if self._draining:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue

                command = await queue.claim_next(
                    consumer_name="runtime_worker",
                    command_types=(
                        RuntimeCommandType.USER_MESSAGE,
                        RuntimeCommandType.REFRESH_LLM_CONFIG,
                        RuntimeCommandType.REFRESH_CHANNELS,
                        RuntimeCommandType.SENSOR_SYNC,
                        RuntimeCommandType.SENSOR_STATE_FLUSH,
                    ),
                )
                if command is None:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue

                self._active_commands += 1
                self._idle_event.clear()
                if command.command_type is RuntimeCommandType.USER_MESSAGE:
                    user_message = command.as_user_message()
                    published = await message_bus.publish(
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
                                # Phase H+1: propagate dispatcher source into
                                # the fact payload so UserMessagePayload.from_dict
                                # can tag the resulting RunTrigger
                                # (api → user_message; telegram/weixin → external_inbound).
                                "source": user_message.source,
                            },
                            source=user_message.source,
                            level=EventLevel.INFO,
                            correlation_id=user_message.correlation_id,
                            metadata={
                                REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY: True,
                            },
                        )
                    )
                elif command.command_type is RuntimeCommandType.REFRESH_LLM_CONFIG:
                    from ..bootstrap.backend import refresh_runtime_llm_config
                    from ..config.loader import reload_config

                    refreshed_config = reload_config()
                    refresh_runtime_llm_config(refreshed_config)
                    published = True
                elif command.command_type is RuntimeCommandType.REFRESH_CHANNELS:
                    from ..config.loader import reload_config

                    reload_config()
                    channels_module = self._context.channels.module
                    if channels_module is not None:
                        await channels_module.restart()
                    published = True
                elif command.command_type is RuntimeCommandType.SENSOR_SYNC:
                    sensor_sync = command.as_sensor_sync()
                    sensor_scheduler = require_initialized(
                        self._context.agent_runtime.sensor_scheduler_contrib,
                        "sensor scheduler contributor",
                    )
                    await sensor_scheduler.queue_manual_sync(sensor_sync.source_name)
                    published = True
                elif command.command_type is RuntimeCommandType.SENSOR_STATE_FLUSH:
                    sensor_flush = command.as_sensor_state_flush()
                    sensor_sync_executor = require_initialized(
                        self._context.agent_runtime.sensor_sync_executor,
                        "sensor sync executor",
                    )
                    await sensor_sync_executor.flush_sensor_state(sensor_flush.source_name)
                    published = True
                else:
                    raise RuntimeError(f"Unsupported runtime command type: {command.command_type}")

                if published:
                    await queue.ack(command.command_id)
                else:
                    await queue.requeue(command.command_id, error_text="LOCAL_MESSAGE_BUS_PUBLISH_FAILED")
                self._active_commands = max(0, self._active_commands - 1)
                if self._active_commands == 0:
                    self._idle_event.set()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._active_commands = max(0, self._active_commands - 1)
                if self._active_commands == 0:
                    self._idle_event.set()
                logger.warning("Runtime command processing failed", error=str(exc))
                await asyncio.sleep(self._poll_interval_seconds)


class PluginIngressProcessorModule(LifecycleModule):
    """Consume persisted plugin ingress events and route them to handlers."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        *,
        handlers: list[PluginIngressHandlerRegistration] | None = None,
        poll_interval_seconds: float = 0.1,
    ):
        super().__init__(
            name="runtime_plugin_ingress_processor",
            dependencies=("runtime_trace", "runtime_plugin_system"),
        )
        self._context = context
        self._poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False
        self._handlers = {
            (registration.plugin_target, registration.event_type): registration.handler
            for registration in (handlers or [])
        }

    async def init(self) -> None:
        plugin_manager = self._context.plugins.plugin_manager
        if plugin_manager is not None:
            runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
            for plugin in plugin_manager.iter_loaded_plugins():
                registrations = plugin.get_plugin_ingress_registrations(runtime_paths=runtime_paths)
                for registration in registrations:
                    self._handlers[(registration.plugin_target, registration.event_type)] = registration.handler
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def shutdown(self) -> None:
        self._running = False
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
                event = await store.claim_next_plugin_ingress_event(consumer_name="runtime_worker")
                if event is None:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue

                await self._dispatch_event(store, event)
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
        handler = self._handlers.get((event.plugin_target, event.event_type))
        if handler is None:
            await store.fail_plugin_ingress_event(
                event.event_id,
                error_text=(
                    f"No plugin ingress handler registered for "
                    f"{event.plugin_target}:{event.event_type}"
                ),
            )
            return

        payload = json.loads(event.payload_json or "{}")
        if not isinstance(payload, dict):
            payload = {}

        try:
            await handler.handle_event(event, payload)
        except Exception as exc:
            await store.fail_plugin_ingress_event(event.event_id, error_text=str(exc))
            return

        await store.complete_plugin_ingress_event(event.event_id)
