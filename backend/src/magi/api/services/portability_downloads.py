"""Read completed portability artifacts through bounded authenticated chunks."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import stat
import threading
from pathlib import Path

from pydantic import BaseModel

from ...memory.portability.operations import MemoryPortabilityOperation
from ...memory.portability.service import get_memory_portability_service
from .file_transfers import CHUNK_BYTES, TransferError

_SLOTS = threading.BoundedSemaphore(2)
_MAX_DOWNLOAD_BYTES = 2 * 1024**3


class OutputMetadata(BaseModel):
    operation_id: str
    name: str
    size: int
    version: str


class OutputChunk(BaseModel):
    operation_id: str
    offset: int
    version: str
    data: str
    sha256: str


def _operation(operation_id: str) -> MemoryPortabilityOperation:
    operation = get_memory_portability_service().get_operation(operation_id)
    if operation is None or operation.kind not in {"backup", "export"} or operation.status != "succeeded" or not operation.output_path:
        raise TransferError("output_not_available", 404)
    return operation


def _metadata(operation: MemoryPortabilityOperation, file_stat: os.stat_result) -> OutputMetadata:
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > _MAX_DOWNLOAD_BYTES:
        raise TransferError("output_not_downloadable", 413)
    if file_stat.st_size != operation.file_size_bytes:
        raise TransferError("output_changed", 409)
    identity = f"{file_stat.st_dev}:{file_stat.st_ino}:{file_stat.st_size}:{file_stat.st_mtime_ns}:{file_stat.st_ctime_ns}"
    return OutputMetadata(operation_id=operation.operation_id, name=Path(operation.output_path).name,
                          size=file_stat.st_size, version=hashlib.sha256(identity.encode()).hexdigest())


def _read(operation: MemoryPortabilityOperation, offset: int | None, version: str | None) -> OutputMetadata | OutputChunk:
    if not _SLOTS.acquire(blocking=False):
        raise TransferError("output_busy", 503)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(operation.output_path, flags), "rb") as source:
            metadata = _metadata(operation, os.fstat(source.fileno()))
            if offset is None:
                return metadata
            if metadata.version != version:
                raise TransferError("output_changed", 409)
            if offset < 0 or offset >= metadata.size:
                raise TransferError("invalid_output_offset", 416)
            source.seek(offset)
            data = source.read(min(CHUNK_BYTES, metadata.size - offset))
            if len(data) != min(CHUNK_BYTES, metadata.size - offset) or _metadata(operation, os.fstat(source.fileno())).version != version:
                raise TransferError("output_changed", 409)
            return OutputChunk(operation_id=operation.operation_id, offset=offset, version=version,
                               data=base64.b64encode(data).decode("ascii"), sha256=hashlib.sha256(data).hexdigest())
    except OSError as error:
        raise TransferError("output_unavailable", 404) from error
    finally:
        _SLOTS.release()


async def describe_output(operation_id: str) -> OutputMetadata:
    """Describe an artifact by operation ID without exposing a filesystem read API."""
    operation = _operation(operation_id)
    result = await asyncio.to_thread(_read, operation, None, None)
    assert isinstance(result, OutputMetadata)
    return result


async def read_output_chunk(operation_id: str, offset: int, version: str) -> OutputChunk:
    """Read one version-checked chunk without buffering the entire artifact."""
    operation = _operation(operation_id)
    result = await asyncio.to_thread(_read, operation, offset, version)
    assert isinstance(result, OutputChunk)
    return result
