"""Bounded snapshot transport around atomic repository imports."""

from __future__ import annotations

import base64
import hashlib
import tempfile
from typing import Any, BinaryIO
from uuid import uuid4

from pydantic import BaseModel

from .storage import StorageCall, StorageResult

CHUNK_BYTES = 128 * 1024
MAX_SNAPSHOT_BYTES = 1024 * 1024 * 1024


class SnapshotTransport:
    def __init__(self, transfer: Any, snapshot_type: type[BaseModel]) -> None:
        self._transfer = transfer
        self._snapshot_type = snapshot_type
        self._export: tuple[str, BinaryIO, int] | None = None
        self._import: tuple[str, BinaryIO, int, str, bool] | None = None

    async def invoke(self, request: StorageCall) -> StorageResult:
        args = request.arguments
        operation = request.operation
        if operation == "export_begin" and not args:
            if self._export is not None:
                raise ValueError("A snapshot export is already open")
            snapshot = await self._transfer.export_state()
            payload = self._snapshot_type.model_validate(snapshot).model_dump_json().encode()
            if len(payload) > MAX_SNAPSHOT_BYTES:
                raise ValueError("Snapshot exceeds the transfer limit")
            stream = tempfile.TemporaryFile()
            try:
                stream.write(payload)
                token = uuid4().hex
                self._export = token, stream, len(payload)
                return StorageResult(value={"token": token, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
            except BaseException:
                stream.close()
                raise
        if operation == "export_read" and set(args) == {"token", "offset"}:
            if self._export is None or args["token"] != self._export[0]:
                raise ValueError("Snapshot export is unavailable")
            _, stream, size = self._export
            offset = args["offset"]
            if type(offset) is not int or not 0 <= offset <= size:
                raise ValueError("Invalid snapshot offset")
            stream.seek(offset)
            return StorageResult(value=base64.b64encode(stream.read(CHUNK_BYTES)).decode("ascii"))
        if operation == "export_close" and set(args) == {"token"}:
            if self._export is None or args["token"] != self._export[0]:
                raise ValueError("Snapshot export is unavailable")
            self._export[1].close()
            self._export = None
            return StorageResult()
        if operation == "import_begin" and set(args) == {"size", "sha256", "replace"}:
            size, digest, replace = args["size"], args["sha256"], args["replace"]
            if self._import is not None:
                raise ValueError("A snapshot import is already open")
            if type(size) is not int or not 0 < size <= MAX_SNAPSHOT_BYTES or type(replace) is not bool:
                raise ValueError("Invalid snapshot import parameters")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid snapshot checksum")
            token = uuid4().hex
            self._import = token, tempfile.TemporaryFile(), size, digest, replace
            return StorageResult(value={"token": token})
        if operation == "import_write" and set(args) == {"token", "offset", "content"}:
            if self._import is None or args["token"] != self._import[0]:
                raise ValueError("Snapshot import is unavailable")
            _, stream, size, _, _ = self._import
            content, offset = args["content"], args["offset"]
            if type(offset) is not int or offset != stream.tell() or not isinstance(content, str) or len(content) > CHUNK_BYTES * 2:
                raise ValueError("Invalid snapshot chunk")
            chunk = base64.b64decode(content, validate=True)
            if not chunk or len(chunk) > CHUNK_BYTES or stream.tell() + len(chunk) > size:
                raise ValueError("Invalid snapshot chunk size")
            stream.write(chunk)
            return StorageResult()
        if operation in {"import_commit", "import_abort"} and set(args) == {"token"}:
            if self._import is None or args["token"] != self._import[0]:
                raise ValueError("Snapshot import is unavailable")
            _, stream, size, digest, replace = self._import
            self._import = None
            try:
                if operation == "import_commit":
                    if stream.tell() != size:
                        raise ValueError("Snapshot import is incomplete")
                    stream.seek(0)
                    payload = stream.read()
                    if hashlib.sha256(payload).hexdigest() != digest:
                        raise ValueError("Snapshot checksum mismatch")
                    snapshot = self._snapshot_type.model_validate_json(payload)
                    await self._transfer.import_state(snapshot, replace=replace)
                return StorageResult()
            finally:
                stream.close()
        return StorageResult(error="invalid")

    def close(self) -> None:
        for entry in (self._export, self._import):
            if entry is not None:
                entry[1].close()
        self._export = self._import = None
