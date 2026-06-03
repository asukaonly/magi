"""Lifecycle module for external messaging channels.

Phase G+1: the legacy ``NotificationRelay`` polling path is retired —
delivery now flows through ``DeliveryRouter`` on the write path. This
module always registers ``ChatSseChannel`` under the ``"chat_sse"`` key
so the chat UI keeps receiving streaming/final notifications even when
no plugin channels are loaded.

The ``_relay`` / ``_relay_task`` fields are kept as ``None`` for
backward-compat with any external diagnostics that probe them.
"""

from __future__ import annotations

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger

logger = get_logger(__name__)


class ChannelsModule(LifecycleModule):
    """Initialize channel plugins and the in-process chat SSE channel."""

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
        # Retired in Phase G+1 — kept as None so external diagnostics that
        # probe ``module._relay`` / ``module._relay_task`` don't AttributeError.
        self._relay_task = None
        self._registry = None
        self._relay = None
        self._session_mapper = None
        self._receipts_store = None

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
        from .attachments import ChannelAttachmentStore
        from .chat_sse_channel import ChatSseChannel
        from .dispatcher import ChannelMessageDispatcher
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

        # Phase G+1: chat_sse must register even in solo deployments
        # (no plugin channels) — the chat UI depends on the runtime_trace
        # rows that ``ChatSseChannel.deliver`` writes. So we proceed
        # unconditionally and only set up the plugin-binding facades when
        # there are plugin channels that need them.
        channels_db_path = str(runtime_paths.data_dir / "channels" / "channels.db")
        from pathlib import Path
        Path(channels_db_path).parent.mkdir(parents=True, exist_ok=True)

        # Identity layer (L1): pull the active resolver off the bootstrap
        # context. IdentityModule initialized earlier in the lifecycle
        # (infrastructure phase) so it's always present in production;
        # tests / partial bootstraps may omit it, in which case the
        # mapper falls back to CANONICAL_LOCAL_USER (single-user default).
        identity_resolver = getattr(self._context.identity, "resolver", None)
        session_mapper = ChannelSessionMapper(
            db_path=channels_db_path,
            chat_store=chat_store,
            identity_resolver=identity_resolver,
        )
        await session_mapper.initialize()

        from .receipts_store import DeliveryReceiptsStore
        self._receipts_store = DeliveryReceiptsStore(db_path=channels_db_path)
        await self._receipts_store.initialize()
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

        # Always register the in-process chat SSE channel. It writes
        # directly to runtime_trace_store, which the chat UI polls — so the
        # NotificationRelay polling fan-out is no longer required for chat.
        chat_sse_channel = ChatSseChannel(trace_store=trace_store)
        try:
            registry.register(chat_sse_channel)
        except ValueError:
            logger.warning("chat_sse channel already registered, skipping duplicate")

        await registry.start_all()

        self._registry = registry
        self._session_mapper = session_mapper
        logger.info(
            "Channels module started",
            plugin_channel_count=len(channel_instances),
            chat_sse_registered=True,
        )

    async def _stop_channels(self) -> None:
        if self._registry is not None:
            await self._registry.stop_all()
        self._registry = None
        self._session_mapper = None
        logger.info("Channels module stopped")
