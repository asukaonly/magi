from dataclasses import dataclass
from typing import Protocol

import pytest

from magi.db.storage_proxy import RepositoryProxy
from magi.db.storage_transfer_proxy import StorageTransferProxy
from magi_plugin_sdk.storage_dispatch import RepositoryDispatcher
from magi_plugin_sdk.storage_transfer import SnapshotTransport, CHUNK_BYTES
from magi_plugin_sdk.storage_models.channels import ChannelStorageSnapshot, RelayCursorRecord


@dataclass
class Record:
    identifier: str
    revision: int


class Port(Protocol):
    async def save(self, record: Record, *, replace: bool = False) -> Record: ...


class Repository:
    async def save(self, record: Record, *, replace: bool = False) -> Record:
        assert isinstance(record, Record)
        return record


class Provider:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher

    async def invoke(self, request):
        return await self.dispatcher.invoke(request)


@pytest.mark.asyncio
async def test_proxy_roundtrip_preserves_typed_domain_values():
    dispatcher = RepositoryDispatcher({"records": Repository()}, {"records": ("save",)}, {"records": Port})
    proxy = RepositoryProxy(Provider(dispatcher), "session", "records", Port)
    assert await proxy.save(Record("a", 2)) == Record("a", 2)
    with pytest.raises(AttributeError):
        await proxy.execute_sql("DELETE FROM records")


class Transfer:
    def __init__(self):
        self.snapshot = ChannelStorageSnapshot(relay_cursors=[
            RelayCursorRecord(state_key="x" * (CHUNK_BYTES + 1), value_integer=2, updated_at_ms=3),
        ])

    async def export_state(self):
        return self.snapshot

    async def import_state(self, snapshot, *, replace=False):
        assert replace
        self.snapshot = snapshot


@pytest.mark.asyncio
async def test_transfer_proxy_preserves_complete_snapshot_over_multiple_frames():
    transfer = Transfer()
    endpoint = SnapshotTransport(transfer, ChannelStorageSnapshot)
    proxy = StorageTransferProxy(Provider(endpoint), "session", ChannelStorageSnapshot)
    try:
        snapshot = await proxy.export_state()
        assert snapshot == transfer.snapshot
        transfer.snapshot = ChannelStorageSnapshot()
        await proxy.import_state(snapshot, replace=True)
        assert transfer.snapshot == snapshot
    finally:
        endpoint.close()
