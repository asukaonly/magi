"""L3 Message Bus lifecycle module."""

from __future__ import annotations

import asyncio

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .contracts import RuntimeCommandType
from .events import Event, EventLevel, EventTypes
from .memory_backend import MemoryMessageBackend
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
        self._context.message_bus.message_bus = MemoryMessageBackend(
            max_queue_size=config.agent.message_bus.max_queue_size,
            num_workers=config.agent.message_bus.num_workers,
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
                        RuntimeCommandType.TIMELINE_SOURCE_SYNC,
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
                            },
                            source=user_message.source,
                            level=EventLevel.INFO,
                            correlation_id=user_message.correlation_id,
                        )
                    )
                elif command.command_type is RuntimeCommandType.REFRESH_LLM_CONFIG:
                    from ..bootstrap.backend import refresh_runtime_llm_config
                    from ..config.loader import reload_config

                    refreshed_config = reload_config()
                    refresh_runtime_llm_config(refreshed_config)
                    published = True
                elif command.command_type is RuntimeCommandType.TIMELINE_SOURCE_SYNC:
                    timeline_sync = command.as_timeline_source_sync()
                    timeline_scheduler = require_initialized(
                        self._context.timeline.timeline_scheduler_contrib,
                        "timeline scheduler contributor",
                    )
                    await timeline_scheduler.queue_manual_sync(timeline_sync.source_name)
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
