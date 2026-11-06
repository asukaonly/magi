import pytest

from magi.plugins.storage_registry import PluginStorageRegistry
from magi_plugin_sdk.storage import StorageProviderSpec


class Provider:
    async def open(self, request): ...
    async def invoke(self, request): ...
    async def close(self, session_id): ...


def test_storage_binding_protects_exact_connection_lifetime():
    registry = PluginStorageRegistry()
    spec = StorageProviderSpec(provider_id="mysql", domains=["chat"])
    provider = Provider()
    dispose = registry.register(plugin_id="storage-mysql", connection_id="primary", spec=spec, provider=provider)
    assert registry.resolve("primary", "mysql", "chat").provider is provider
    with pytest.raises(ValueError, match="selected domain"):
        registry.resolve("primary", "mysql", "memory_events")
    with pytest.raises(ValueError, match="already registered"):
        registry.register(plugin_id="storage-mysql", connection_id="primary", spec=spec, provider=Provider())
    registry.pin("primary")
    with pytest.raises(ValueError, match="offline maintenance"):
        dispose()
    registry.require_mutable("unrelated")
    registry.release("primary")
    dispose()
    with pytest.raises(KeyError):
        registry.resolve("primary", "mysql", "chat")
