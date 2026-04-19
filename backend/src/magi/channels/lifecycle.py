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

        registry = ChannelRegistry()
        for channel in channel_instances:
            channel.bind_session_mapper(session_mapper)
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



class ChannelsModule(LifecycleModule):
    """Initialize configured external messaging channels and the notification relay."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_channels",
            dependencies=(
                "runtime_chat_store",
                "runtime_trace",
                "runtime_configuration",
                "runtime_core_dependencies",
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
        """Tear down running channels and re-initialize from current config."""
        logger.info("Restarting channels module after configuration change")
        await self._stop_channels()
        # Re-read config (already reloaded by command processor)
        await self._start_channels()

    async def shutdown(self) -> None:
        await self._stop_channels()
        self._context.channels.module = None

    async def _start_channels(self) -> None:
        from .notification_relay import NotificationRelay
        from .registry import ChannelRegistry
        from .session_mapper import ChannelSessionMapper

        config = require_initialized(self._context.core.config, "config")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        chat_store = require_initialized(self._context.chat.store, "chat store")
        trace_store = require_initialized(self._context.runtime_trace.store, "runtime trace store")

        tg_config = config.channels.telegram
        if not tg_config.enabled:
            logger.info("No channels enabled, skipping channel bootstrap")
            return

        channels_db_path = str(runtime_paths.data_dir / "channels" / "channels.db")
        # Ensure parent directory exists
        from pathlib import Path
        Path(channels_db_path).parent.mkdir(parents=True, exist_ok=True)

        session_mapper = ChannelSessionMapper(db_path=channels_db_path, chat_store=chat_store)
        await session_mapper.initialize()

        registry = ChannelRegistry()

        if tg_config.enabled and tg_config.bot_token:
            from .telegram.adapter import TelegramChannel, TelegramChannelConfig

            # Resolve proxy: channel-specific > global network proxy
            proxy = tg_config.proxy
            if not proxy:
                proxy = config.network.proxy_url() or ""

            adapter_config = TelegramChannelConfig(
                bot_token=tg_config.bot_token,
                mode=tg_config.mode,
                webhook_url=tg_config.webhook_url,
                webhook_secret=tg_config.webhook_secret,
                proxy=proxy,
                allowed_user_ids=list(tg_config.allowed_user_ids),
                group_trigger_keyword=tg_config.group_trigger_keyword,
                magi_user_id=tg_config.magi_user_id,
                max_message_length=tg_config.max_message_length,
            )
            tg_channel = TelegramChannel(
                config=adapter_config,
                session_mapper=session_mapper,
            )
            registry.register(tg_channel)

        if not registry.all_channels():
            logger.info("No channel adapters configured")
            return

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
        logger.info("Channels module started")

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
