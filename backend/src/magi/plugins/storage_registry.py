"""Connection-owned storage contributions with explicit lifetime protection."""

from collections.abc import Callable
from dataclasses import dataclass

from magi_plugin_sdk.storage import StorageDomain, StorageProvider, StorageProviderSpec


@dataclass(frozen=True)
class StorageContribution:
    plugin_id: str
    connection_id: str
    spec: StorageProviderSpec
    provider: StorageProvider


class PluginStorageRegistry:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], StorageContribution] = {}
        self._pins: set[str] = set()

    def register(
        self, *, plugin_id: str, connection_id: str,
        spec: StorageProviderSpec, provider: StorageProvider,
    ) -> Callable[[], None]:
        key = (connection_id, spec.provider_id)
        if key in self._entries:
            raise ValueError("Storage contribution is already registered")
        if any(not callable(getattr(provider, method, None)) for method in ("open", "invoke", "close")):
            raise ValueError("Storage provider does not implement its public protocol")
        entry = StorageContribution(plugin_id, connection_id, spec, provider)
        self._entries[key] = entry

        def dispose() -> None:
            self.require_mutable(connection_id)
            if self._entries.get(key) is entry:
                del self._entries[key]

        return dispose

    def resolve(self, connection_id: str, provider_id: str, domain: StorageDomain) -> StorageContribution:
        entry = self._entries[(connection_id, provider_id)]
        if domain not in entry.spec.domains:
            raise ValueError("Storage provider does not support the selected domain")
        return entry

    def pin(self, connection_id: str) -> None:
        if not any(key[0] == connection_id for key in self._entries):
            raise KeyError(connection_id)
        self._pins.add(connection_id)

    def release(self, connection_id: str) -> None:
        self._pins.discard(connection_id)

    def require_mutable(self, connection_id: str) -> None:
        if connection_id in self._pins:
            raise ValueError("Active storage requires offline maintenance before replacement")
