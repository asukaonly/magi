"""Typed storage calls over the existing supervised plugin transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from magi_plugin_sdk.storage import (
    StorageCall, StorageOpen, StorageOpened, StorageResult,
)

from ..core.persistence_errors import PersistenceUnavailableError


if TYPE_CHECKING:
    from .process_runtime import ProcessPluginProxy


class StorageProviderProxy:
    def __init__(self, process: ProcessPluginProxy, target: str) -> None:
        self._process = process
        self._target = target

    async def open(self, request: StorageOpen) -> StorageOpened:
        return StorageOpened.model_validate(
            await self._process.invoke(self._target, "open", request)
        )

    async def invoke(self, request: StorageCall) -> StorageResult:
        return await self.invoke_with_host(request, None)

    async def close(self, session_id: str) -> None:
        await self._process.invoke(self._target, "close", session_id)

    async def invoke_with_host(self, request: StorageCall, handler: Callable[..., Any] | None) -> StorageResult:
        from .process_runtime import PluginProcessError
        try:
            return StorageResult.model_validate(await self._process.invoke(
                self._target, "invoke", request, storage_handler=handler,
            ))
        except PluginProcessError as exc:
            raise PersistenceUnavailableError("Storage operation could not be confirmed") from exc

    def invoke_sync_with_host(self, request: StorageCall, handler: Callable[..., Any] | None) -> StorageResult:
        from .process_runtime import PluginProcessError
        try:
            return StorageResult.model_validate(self._process.invoke_sync(
                self._target, "invoke", request, storage_handler=handler,
            ))
        except PluginProcessError as exc:
            raise PersistenceUnavailableError("Storage operation could not be confirmed") from exc
