"""Stream complete logical snapshots through bounded storage messages."""

from __future__ import annotations

import base64
import hashlib
import tempfile
from typing import Generic, TypeVar

from pydantic import BaseModel

from magi_plugin_sdk.storage import StorageCall, StorageProvider
from magi_plugin_sdk.storage_transfer import CHUNK_BYTES, MAX_SNAPSHOT_BYTES

from ..core.async_cleanup import finish_cleanup
from ..core.persistence_errors import PersistenceUnavailableError

Snapshot = TypeVar("Snapshot", bound=BaseModel)


class StorageTransferProxy(Generic[Snapshot]):
    def __init__(self, provider: StorageProvider, session_id: str, snapshot_type: type[Snapshot]) -> None:
        self._provider = provider
        self._session_id = session_id
        self._snapshot_type = snapshot_type

    async def _call(self, operation: str, **arguments):
        reply = await self._provider.invoke(StorageCall(
            session_id=self._session_id, repository="transfer", operation=operation, arguments=arguments,
        ))
        if reply.error in {"unavailable", "outcome_unknown"}:
            raise PersistenceUnavailableError("Storage transfer could not be confirmed")
        if reply.error is not None:
            raise ValueError("Storage transfer was rejected")
        return reply.value

    async def export_state(self) -> Snapshot:
        opened = await self._call("export_begin")
        if not isinstance(opened, dict) or set(opened) != {"token", "size", "sha256"}:
            raise ValueError("Invalid snapshot export descriptor")
        token, size, digest = opened["token"], opened["size"], opened["sha256"]
        if not isinstance(token, str) or type(size) is not int or not 0 < size <= MAX_SNAPSHOT_BYTES or not isinstance(digest, str):
            raise ValueError("Invalid snapshot export bounds")
        try:
            with tempfile.TemporaryFile() as stream:
                offset = 0
                checksum = hashlib.sha256()
                while offset < size:
                    value = await self._call("export_read", token=token, offset=offset)
                    if not isinstance(value, str) or len(value) > CHUNK_BYTES * 2:
                        raise ValueError("Invalid snapshot export chunk")
                    chunk = base64.b64decode(value, validate=True)
                    if not chunk or len(chunk) > CHUNK_BYTES or offset + len(chunk) > size:
                        raise ValueError("Invalid snapshot export length")
                    stream.write(chunk)
                    checksum.update(chunk)
                    offset += len(chunk)
                if checksum.hexdigest() != digest:
                    raise ValueError("Snapshot export checksum mismatch")
                stream.seek(0)
                return self._snapshot_type.model_validate_json(stream.read())
        finally:
            await finish_cleanup(self._call("export_close", token=token))

    async def import_state(self, snapshot: Snapshot, *, replace: bool = False) -> None:
        payload = snapshot.model_dump_json().encode()
        if len(payload) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Snapshot exceeds the transfer limit")
        opened = await self._call("import_begin", size=len(payload), sha256=hashlib.sha256(payload).hexdigest(), replace=replace)
        if not isinstance(opened, dict) or set(opened) != {"token"} or not isinstance(opened["token"], str):
            raise ValueError("Invalid snapshot import descriptor")
        token = opened["token"]
        committing = False
        try:
            for offset in range(0, len(payload), CHUNK_BYTES):
                await self._call("import_write", token=token, offset=offset, content=base64.b64encode(payload[offset:offset + CHUNK_BYTES]).decode("ascii"))
            committing = True
            await self._call("import_commit", token=token)
        finally:
            if not committing:
                await finish_cleanup(self._call("import_abort", token=token))
