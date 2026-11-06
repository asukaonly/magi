import pytest
from pydantic import ValidationError

from magi_plugin_sdk import Plugin
from magi_plugin_sdk.storage import (
    StorageCall, StorageOpen, StorageOpened, StorageProviderSpec, StorageResult,
)
from magi_plugin_sdk.transport import decode, encode
from magi_plugin_sdk.worker_catalog import WorkerCatalog


class Provider:
    async def open(self, request):
        return StorageOpened(session_id="owner", target_identity="database", schema_version="1")

    async def invoke(self, request):
        return StorageResult(value=request.arguments)

    async def close(self, session_id):
        pass


class StoragePlugin(Plugin):
    def get_storage_providers(self):
        return [(StorageProviderSpec(provider_id="test", domains=["chat"]), Provider())]


@pytest.mark.parametrize("value", [
    StorageProviderSpec(provider_id="mysql", domains=["chat", "channels", "memory_events"]),
    StorageOpen(domain="chat", center_id="center", mode="maintenance"),
    StorageOpened(session_id="session", target_identity="target", schema_version="v1"),
    StorageCall(session_id="session", repository="chat", operation="get_turn", arguments={"turn_id": "turn"}),
    StorageResult(error="outcome_unknown"),
])
def test_storage_values_roundtrip(value):
    assert decode(encode(value)) == value


def test_storage_rejects_unsupported_contract_and_private_calls():
    with pytest.raises(ValidationError):
        StorageProviderSpec(provider_id="test", contract_version=2, domains=["chat"])
    with pytest.raises(ValidationError):
        StorageProviderSpec(provider_id="test", domains=["chat", "chat"])
    with pytest.raises(ValidationError):
        StorageCall(session_id="s", repository="chat", operation="__dict__")
    with pytest.raises(ValidationError):
        StorageOpen(domain="chat", center_id="c", mode="runtime", connection={})


def test_worker_exposes_only_storage_lifecycle_methods(tmp_path):
    plugin = StoragePlugin()
    catalog = WorkerCatalog(plugin)
    entries = catalog.describe()["get_storage_providers"]
    assert entries[0]["spec"].domains == ["chat"]
    assert callable(catalog.method(entries[0]["target"], "invoke"))
    with pytest.raises(PermissionError):
        catalog.method(entries[0]["target"], "__dict__")


def test_worker_rejects_incomplete_provider(tmp_path):
    plugin = StoragePlugin()
    plugin.get_storage_providers = lambda: [(StorageProviderSpec(provider_id="test", domains=["chat"]), object())]
    with pytest.raises(ValueError, match="public protocol"):
        WorkerCatalog(plugin).describe()
