"""Bounded, restart-safe staging for owner-uploaded import and restore files."""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...utils.runtime import get_runtime_paths

CHUNK_BYTES = 1024 * 1024
_MAX_TOTAL_BYTES = 8 * 1024**3
_MAX_RESOURCES = 1000
_TTL_SECONDS = 24 * 3600
_LOCK = threading.Lock()


class TransferError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class UploadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: str
    name: str = Field(min_length=1, max_length=255)
    source_name: str = Field(min_length=1, max_length=4096)
    last_modified_ms: int = Field(ge=0, le=253402300799000)
    purpose: Literal["history", "restore"]
    size: int = Field(ge=0, le=2 * 1024**3)


class UploadState(UploadSpec):
    received: int
    expires_at: float


def _root() -> Path:
    root = get_runtime_paths().runtime_dir / "file-transfers"
    root.mkdir(mode=0o700, exist_ok=True)
    return root


def _id(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except ValueError as error:
        raise TransferError("invalid_resource_id") from error
    if canonical != value:
        raise TransferError("invalid_resource_id")
    return value


def _read(resource_id: str) -> UploadState:
    path = _root() / _id(resource_id) / "state.json"
    try:
        state = UploadState.model_validate_json(path.read_bytes())
    except FileNotFoundError as error:
        raise TransferError("resource_not_found", 404) from error
    if state.resource_id != resource_id or state.expires_at < time.time():
        raise TransferError("resource_expired", 410)
    return state


def _save(directory: Path, state: UploadState) -> None:
    temporary = directory / "state.tmp"
    with temporary.open("w") as output:
        output.write(state.model_dump_json())
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, directory / "state.json")


def _cleanup_and_size(root: Path) -> tuple[int, int]:
    count = total = 0
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            state = UploadState.model_validate_json((directory / "state.json").read_bytes())
            expired = state.expires_at < time.time()
        except (ValueError, OSError):
            # Incomplete creation from a crash reserves space until its TTL elapses.
            expired = directory.stat().st_mtime < time.time() - _TTL_SECONDS
            state = None
        if expired:
            shutil.rmtree(directory)
        else:
            count += 1
            total += state.size if state else 2 * 1024**3
    return count, total


def _begin(spec: UploadSpec) -> UploadState:
    _id(spec.resource_id)
    if spec.name in {".", ".."} or any(c in spec.name for c in '/\\\0') or any(ord(c) < 32 for c in spec.name):
        raise TransferError("invalid_resource_name")
    if any(part in {"", ".", ".."} for part in spec.source_name.split("/")) or "\\" in spec.source_name or any(ord(c) < 32 for c in spec.source_name):
        raise TransferError("invalid_resource_name")
    if spec.purpose == "history" and spec.size > 256 * 1024**2:
        raise TransferError("history_resource_too_large", 413)
    root = _root()
    directory = root / spec.resource_id
    if directory.exists():
        state = _read(spec.resource_id)
        if any(getattr(state, key) != value for key, value in spec.model_dump().items()):
            raise TransferError("resource_identity_conflict", 409)
        return state
    count, total = _cleanup_and_size(root)
    if count >= _MAX_RESOURCES or total + spec.size > _MAX_TOTAL_BYTES:
        raise TransferError("resource_storage_full", 413)
    directory.mkdir(mode=0o700)
    (directory / "content").mkdir(mode=0o700)
    (directory / "content" / spec.name).touch(mode=0o600, exist_ok=False)
    os.utime(directory / "content" / spec.name, (spec.last_modified_ms / 1000, spec.last_modified_ms / 1000))
    state = UploadState(**spec.model_dump(), received=0, expires_at=time.time() + _TTL_SECONDS)
    _save(directory, state)
    return state


def _append(resource_id: str, offset: int, data: bytes, digest: str) -> UploadState:
    if not data or len(data) > CHUNK_BYTES or hashlib.sha256(data).hexdigest() != digest:
        raise TransferError("invalid_resource_chunk")
    state = _read(resource_id)
    if offset < 0 or offset + len(data) > state.size:
        raise TransferError("invalid_resource_offset", 409)
    path = _root() / resource_id / "content" / state.name
    with path.open("r+b") as output:
        if offset < state.received:
            output.seek(offset)
            if offset + len(data) <= state.received and output.read(len(data)) == data:
                return state
            raise TransferError("resource_chunk_conflict", 409)
        if offset != state.received:
            raise TransferError("invalid_resource_offset", 409)
        # Truncate an unacknowledged tail left by a crash before metadata commit.
        output.truncate(state.received)
        output.seek(offset)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    state.received += len(data)
    if state.received == state.size:
        os.utime(path, (state.last_modified_ms / 1000, state.last_modified_ms / 1000))
    state.expires_at = time.time() + _TTL_SECONDS
    _save(path.parent.parent, state)
    return state


def _run(operation):
    # Reject saturation instead of accumulating filesystem work in the executor.
    if not _LOCK.acquire(blocking=False):
        raise TransferError("resource_busy", 503)
    try:
        return operation()
    except OSError as error:
        raise TransferError("resource_storage_unavailable", 503) from error
    finally:
        _LOCK.release()


async def begin_upload(spec: UploadSpec) -> UploadState:
    """Reserve a bounded upload using a client-generated idempotency key."""
    return await asyncio.to_thread(_run, lambda: _begin(spec))


async def append_upload(resource_id: str, offset: int, data: bytes, digest: str) -> UploadState:
    """Commit or acknowledge an identical repeated chunk after network loss."""
    return await asyncio.to_thread(_run, lambda: _append(resource_id, offset, data, digest))


async def resolve_uploaded_files(resource_ids: list[str], purpose: Literal["history", "restore"]) -> list[Path]:
    """Resolve complete resources of the expected purpose without accepting client paths."""
    def resolve() -> list[Path]:
        result = []
        for resource_id in resource_ids:
            state = _read(resource_id)
            if state.purpose != purpose or state.received != state.size:
                raise TransferError("resource_not_ready", 409)
            path = _root() / resource_id / "content" / state.name
            if path.stat().st_size != state.size:
                raise TransferError("resource_integrity_error", 409)
            result.append(path.resolve(strict=True))
        return result
    return await asyncio.to_thread(_run, resolve)


async def uploaded_source_names(resource_ids: list[str]) -> dict[str, str]:
    """Preserve selected relative names independently of staging paths."""
    def names() -> dict[str, str]:
        result = {}
        for resource_id in resource_ids:
            state = _read(resource_id)
            result[str((_root() / resource_id / "content" / state.name).resolve(strict=True))] = state.source_name
        return result
    return await asyncio.to_thread(_run, names)


async def clear_uploaded_files() -> dict[str, int]:
    """Remove staged user content inside the center full-clear barrier."""
    def clear() -> dict[str, int]:
        root = _root()
        count = sum(1 for _ in root.iterdir())
        shutil.rmtree(root)
        return {"uploaded_file_resources": count}
    return await asyncio.to_thread(_run, clear)
