import base64
import hashlib

import pytest
from pydantic import BaseModel

from magi_plugin_sdk.storage import StorageCall
from magi_plugin_sdk.storage_transfer import CHUNK_BYTES, SnapshotTransport


class Snapshot(BaseModel):
    value: str


class Transfer:
    def __init__(self, value):
        self.snapshot = Snapshot(value=value)
        self.imports = []

    async def export_state(self):
        return self.snapshot

    async def import_state(self, snapshot, *, replace=False):
        self.imports.append((snapshot, replace))


def request(operation, **arguments):
    return StorageCall(session_id="s", repository="transfer", operation=operation, arguments=arguments)


@pytest.mark.asyncio
async def test_snapshot_transfer_chunks_and_commits_only_after_validation():
    source = Transfer("x" * (CHUNK_BYTES * 2 + 1))
    target = Transfer("old")
    reader, writer = SnapshotTransport(source, Snapshot), SnapshotTransport(target, Snapshot)
    try:
        export = (await reader.invoke(request("export_begin"))).value
        imported = (await writer.invoke(request("import_begin", size=export["size"], sha256=export["sha256"], replace=True))).value
        offset = 0
        while offset < export["size"]:
            chunk = (await reader.invoke(request("export_read", token=export["token"], offset=offset))).value
            await writer.invoke(request("import_write", token=imported["token"], offset=offset, content=chunk))
            assert not target.imports
            offset += len(base64.b64decode(chunk))
        await writer.invoke(request("import_commit", token=imported["token"]))
        assert target.imports == [(source.snapshot, True)]
        await reader.invoke(request("export_close", token=export["token"]))
    finally:
        reader.close()
        writer.close()


@pytest.mark.asyncio
async def test_incomplete_or_corrupted_import_does_not_mutate_destination():
    target = Transfer("old")
    writer = SnapshotTransport(target, Snapshot)
    payload = b'{"value":"new"}'
    try:
        for partial, digest in ((True, hashlib.sha256(payload).hexdigest()), (False, "0" * 64)):
            opened = (await writer.invoke(request("import_begin", size=len(payload), sha256=digest, replace=True))).value
            chunk = payload[:-1] if partial else payload
            await writer.invoke(request("import_write", token=opened["token"], offset=0, content=base64.b64encode(chunk).decode()))
            with pytest.raises(ValueError):
                await writer.invoke(request("import_commit", token=opened["token"]))
            assert not target.imports
    finally:
        writer.close()
