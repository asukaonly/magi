"""Host-bundled SQLite contribution, assembled before domain consumers start."""

from typing import Any, Callable, Protocol

from magi_plugin_sdk import Plugin
from magi_plugin_sdk.storage import (
    StorageCall, StorageOpen, StorageOpened, StorageProvider, StorageProviderSpec, StorageResult,
)


class BundledStorageProvider(StorageProvider, Protocol):
    async def invoke_with_host(self, request: StorageCall, handler: Callable[..., Any]) -> StorageResult: ...
    def invoke_sync_with_host(self, request: StorageCall, handler: Callable[..., Any]) -> StorageResult: ...
    async def shutdown(self) -> None: ...


class SqliteStoragePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__()
        self._provider: BundledStorageProvider | None = None

    def bind_provider(self, provider: BundledStorageProvider) -> None:
        if self._provider is not None:
            raise RuntimeError("SQLite storage is already assembled")
        self._provider = provider

    def get_storage_providers(self) -> list[tuple[StorageProviderSpec, StorageProvider]]:
        return [(StorageProviderSpec(
            provider_id="sqlite", target_identity="local-sqlite-v1",
            domains=["chat", "memory_events", "channels"],
        ), self)]

    def _require_provider(self) -> BundledStorageProvider:
        if self._provider is None:
            raise RuntimeError("SQLite storage must be assembled by the host startup owner")
        return self._provider

    async def open(self, request: StorageOpen) -> StorageOpened:
        return await self._require_provider().open(request)

    async def invoke(self, request: StorageCall) -> StorageResult:
        return await self._require_provider().invoke(request)

    async def close(self, session_id: str) -> None:
        await self._require_provider().close(session_id)

    async def invoke_with_host(self, request: StorageCall, handler: Callable[..., Any]) -> StorageResult:
        return await self._require_provider().invoke_with_host(request, handler)

    def invoke_sync_with_host(self, request: StorageCall, handler: Callable[..., Any]) -> StorageResult:
        return self._require_provider().invoke_sync_with_host(request, handler)

    async def shutdown(self) -> None:
        await self._require_provider().shutdown()
