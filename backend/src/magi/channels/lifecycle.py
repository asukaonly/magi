"""Lifecycle module for external messaging channels."""

from __future__ import annotations

import asyncio

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger

logger = get_logger(__name__)


class ChannelsModule(LifecycleModule):
    """Initialize channel plugins and the notification relay."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_channels",
            dependencies=(
                "runtime_chat_store",
                "runtime_trace",
                "runtime_configuration",
                "runtime_core_dependencies",
                "runtime_plugin_system",
            ),
        )
        self._context = context
        self._relay_task: asyncio.Task[None] | None = None
        self._registry = None
        self._relay = None
        self._session_mapper = None

    async def init(self) -> None:
        self._context.channels.module = self
        await self._start_channels()

    async def restart(self) -> None:
        """Tear down running channels and re-initialize from current plugin state."""
        logger.info("Restarting channels module")
        await self._stop_channels()
        await self._start_channels()

    async def shutdown(self) -> None:
        await self._stop_channels()
        self._context.channels.module = None

    async def _start_channels(self) -> None:
        from .dispatcher import ChannelMessageDispatcher
        from .attachments import ChannelAttachmentStore
        from .notification_relay import NotificationRelay
        from .registry import ChannelRegistry
        from .session_mapper import ChannelSessionMapper

        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        chat_store = require_initialized(self._context.chat.store, "chat store")
        trace_store = require_initialized(self._context.runtime_trace.store, "runtime trace store")

        # Collect channel instances from loaded plugins.
        channel_instances = []
        for plugin in plugin_manager.iter_loaded_plugins():
            channel = plugin.get_channel()
            if channel is not None:
                channel_instances.append(channel)

        if not channel_instances:
            logger.info("No channel plugins enabled, skipping channel bootstrap")
            return

        channels_db_path = str(runtime_paths.data_dir / "channels" / "channels.db")
        from pathlib import Path
        Path(channels_db_path).parent.mkdir(parents=True, exist_ok=True)

        session_mapper = ChannelSessionMapper(db_path=channels_db_path, chat_store=chat_store)
        await session_mapper.initialize()
        message_dispatcher = ChannelMessageDispatcher()
        attachment_store = ChannelAttachmentStore(runtime_paths=runtime_paths)

        registry = ChannelRegistry()
        for channel in channel_instances:
            channel.bind_session_mapper(session_mapper)
            channel.bind_message_dispatcher(message_dispatcher)
            channel.bind_attachment_store(attachment_store)
            try:
                registry.register(channel)
            except ValueError:
                logger.warning("Duplicate channel type skipped", channel_type=channel.channel_type)

        await registry.start_all()

        relay = NotificationRelay(
            registry=registry,
            session_mapper=session_mapper,
            trace_store=trace_store,
        )
        self._relay_task = asyncio.create_task(relay.run())

        self._registry = registry
        self._relay = relay
        self._session_mapper = session_mapper
        logger.info("Channels module started", channel_count=len(channel_instances))

    async def _stop_channels(self) -> None:
        if self._relay is not None:
            self._relay.stop()
        if self._relay_task is not None:
            self._relay_task.cancel()
            try:
                await self._relay_task
            except asyncio.CancelledError:
                pass
            self._relay_task = None
        if self._registry is not None:
            await self._registry.stop_all()
        self._registry = None
        self._relay = None
        self._session_mapper = None
        logger.info("Channels module stopped")
