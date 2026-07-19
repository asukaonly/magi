"""Atomic writes and identity-safe reads for managed chat asset files."""

from __future__ import annotations

import asyncio
import os
import stat
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import BinaryIO

from ...utils.runtime import RuntimePaths
from .mutations import require_chat_asset_mutation
from .paths import (
    normalize_chat_asset_component,
    resolve_chat_attachment_file,
    resolve_chat_derived_file,
)

CHAT_ASSET_READ_CHUNK_BYTES = 1024 * 1024


def write_managed_chat_asset_atomically(
    target_path: Path,
    content: bytes,
) -> None:
    """Publish complete bytes at one managed path with no partial target."""

    require_chat_asset_mutation()
    target = Path(target_path)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(bytes(content))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _sync_directory(target.parent)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _sync_directory(directory: Path) -> None:
    """Best-effort durability for the atomic directory entry update."""

    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def open_managed_chat_attachment(
    raw_path: object,
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    original_name: object | None = None,
    runtime_paths: RuntimePaths | None = None,
) -> BinaryIO | None:
    """Open one exact attachment and keep its validated file identity."""

    try:
        normalized_attachment_id = normalize_chat_asset_component(
            attachment_id,
            label="attachment_id",
        )
    except ValueError:
        return None

    def resolve() -> Path | None:
        resolved = resolve_chat_attachment_file(
            raw_path,
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=normalized_attachment_id,
            runtime_paths=runtime_paths,
        )
        expected_original_name = str(original_name or "").strip()
        if expected_original_name:
            expected_name = f"{normalized_attachment_id}__{expected_original_name}"
            if resolved is None or resolved.name != expected_name:
                return None
        return resolved

    return _open_resolved_managed_file(resolve)


def open_managed_chat_derived_file(
    raw_path: object,
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    runtime_paths: RuntimePaths | None = None,
) -> BinaryIO | None:
    """Open one exact derived artifact and keep its validated file identity."""

    def resolve() -> Path | None:
        return resolve_chat_derived_file(
            raw_path,
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=attachment_id,
            runtime_paths=runtime_paths,
        )

    return _open_resolved_managed_file(resolve)


def _open_resolved_managed_file(
    resolver: Callable[[], Path | None],
) -> BinaryIO | None:
    path = resolver()
    if path is None:
        return None
    try:
        initial_stat = path.lstat()
    except OSError:
        return None
    if not _is_single_link_regular_file(initial_stat):
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        opened_stat = os.fstat(descriptor)
        resolved_again = resolver()
        if resolved_again != path:
            raise OSError("Managed chat asset path changed while opening")
        final_stat = path.lstat()
        if (
            not _is_single_link_regular_file(opened_stat)
            or not _is_single_link_regular_file(final_stat)
            or not _same_file_identity(initial_stat, opened_stat)
            or not _same_file_identity(opened_stat, final_stat)
        ):
            raise OSError("Managed chat asset identity changed while opening")
        return os.fdopen(descriptor, "rb", closefd=True)
    except (OSError, ValueError):
        os.close(descriptor)
        return None


def _is_single_link_regular_file(file_stat: os.stat_result) -> bool:
    return stat.S_ISREG(file_stat.st_mode) and getattr(file_stat, "st_nlink", 1) == 1


def _same_file_identity(
    left: os.stat_result,
    right: os.stat_result,
) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
    )


async def aopen_managed_chat_attachment(
    raw_path: object,
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    original_name: object | None = None,
    runtime_paths: RuntimePaths | None = None,
) -> BinaryIO | None:
    """Open an attachment off-loop without leaking a late handle on cancel."""

    worker = asyncio.create_task(
        asyncio.to_thread(
            open_managed_chat_attachment,
            raw_path,
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=attachment_id,
            original_name=original_name,
            runtime_paths=runtime_paths,
        )
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            handle = await worker
        except BaseException:
            pass
        else:
            if handle is not None:
                handle.close()
        raise


async def stream_managed_chat_file(
    handle: BinaryIO,
    *,
    chunk_size: int = CHAT_ASSET_READ_CHUNK_BYTES,
) -> AsyncIterator[bytes]:
    """Stream an already-validated handle and close it on every exit path."""

    safe_chunk_size = max(1, int(chunk_size))
    try:
        while chunk := await _read_managed_chat_file_chunk(
            handle,
            safe_chunk_size,
        ):
            yield chunk
    finally:
        handle.close()


async def _read_managed_chat_file_chunk(
    handle: BinaryIO,
    chunk_size: int,
) -> bytes:
    worker = asyncio.create_task(asyncio.to_thread(handle.read, chunk_size))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            await worker
        except BaseException:
            pass
        raise


__all__ = [
    "CHAT_ASSET_READ_CHUNK_BYTES",
    "aopen_managed_chat_attachment",
    "open_managed_chat_attachment",
    "open_managed_chat_derived_file",
    "stream_managed_chat_file",
    "write_managed_chat_asset_atomically",
]
