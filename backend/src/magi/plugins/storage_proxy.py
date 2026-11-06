"""Typed storage calls over the existing supervised plugin transport."""

from __future__ import annotations

from typing import TYPE_CHECKING

from magi_plugin_sdk.storage import (
    StorageCall, StorageOpen, StorageOpened, StorageResult,
)

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
        return StorageResult.model_validate(
            await self._process.invoke(self._target, "invoke", request)
        )

    async def close(self, session_id: str) -> None:
        await self._process.invoke(self._target, "close", session_id)
