"""Host callbacks for clearing one connection without changing global memory."""

from __future__ import annotations

import asyncio

from magi_plugin_sdk import Plugin, PluginConnection, PluginContext
from magi_plugin_sdk.sources import ScopedSourceRuntimePaths
from magi_plugin_sdk.user_content import UserContentClearContext, UserContentClearRequest

from ..awareness.source_store import SourceStore


class ConnectionContentCoordinator:
    """Run after the manager drains the connection's active worker."""

    def __init__(self, source_store: SourceStore, *, timeout_seconds: float = 30.0) -> None:
        self._source_store = source_store
        self._timeout_seconds = timeout_seconds

    async def clear(self, connection: PluginConnection, plugin: Plugin, context: PluginContext) -> None:
        """Keep source progress and previously imported memory while erasing local content."""
        if context.connection.connection_id != connection.connection_id:
            raise ValueError("Content clear context belongs to another connection")
        request = UserContentClearRequest(
            connection_id=connection.connection_id, reason="user_clear_connection_content",
        )
        paths = ScopedSourceRuntimePaths(connection.connection_id, connection.plugin_id, context.state_dir)
        async with asyncio.timeout(self._timeout_seconds):
            await plugin.clear_user_content(UserContentClearContext(
                request=request, runtime_paths=paths, plugin_id=connection.plugin_id,
                connection_id=connection.connection_id, plugin_settings=connection.settings,
            ))
            for source_id, source, _spec in plugin.get_sources():
                await source.clear_user_content(UserContentClearContext(
                    request=request, runtime_paths=paths, plugin_id=connection.plugin_id,
                    connection_id=connection.connection_id, source_id=source_id,
                    plugin_settings=connection.settings,
                ))
            await self._source_store.clear_user_content(connection_id=connection.connection_id)

    async def disconnect(self, connection: PluginConnection) -> None:
        """Fence stale source batches before the manager disposes the connection."""
        await self._source_store.disconnect_connection(connection.connection_id)
