"""Drive accepted source batches through the existing memory ingestion gateway."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any

from magi_plugin_sdk.runtime import PluginConnection
from magi_plugin_sdk.sources import Source

from ..memory.source_ingestion import SourceIngestionBoundary
from .ingestion_gateway import SourceIngestionGateway
from .source_store import PendingSourceBatch, SourceCheckpoint, SourceCheckpointConflict, SourceStore, source_object_identity


class SourceBatchIngestor:
    """Persist source state only after version-specific L1 outcomes are confirmed."""

    def __init__(self, *, store: SourceStore, gateway: SourceIngestionGateway) -> None:
        self.store = store
        self.gateway = gateway

    async def ingest(
        self,
        *,
        connection: PluginConnection,
        source: Source,
        pending: PendingSourceBatch,
        boundary: SourceIngestionBoundary,
        rule_revision: str,
        allowed_edge_whitelist: list[str],
        allow_pre_clear_events: bool = False,
        provenance: dict[str, Any] | None = None,
    ) -> SourceCheckpoint:
        if not rule_revision:
            raise ValueError("Source projection requires an immutable package revision")
        if connection.connection_id != pending.checkpoint.connection_id:
            raise PermissionError("Source batch connection mismatch")
        if source.connection != connection or source.context is None:
            raise PermissionError("Source is not bound to this source connection")
        for change in pending.batch.changes:
            version = await self.store.version(pending.checkpoint, change)
            if change.operation == "delete" or version["receipt"] is not None:
                continue
            fetched = await source.fetch_item(deepcopy(change.payload))
            output = await source.build_output(fetched)
            metadata = await source.extract_metadata(fetched)
            if output.source_type != pending.checkpoint.source_type:
                raise ValueError("Source output changed its declared semantic source type")
            evidence = version.get("evidence_ref")
            if evidence is None:
                raise SourceCheckpointConflict("Source evidence was revoked before memory ingestion")
            object_identity = source_object_identity(connection.connection_id, source.source_id, change.object_id)
            resources = list(change.resources)
            if output.raw_payload_ref:
                output.raw_payload_ref, imported = await self._import_output_resource(
                    connection=connection,
                    source=source,
                    raw_ref=output.raw_payload_ref,
                    declared=resources,
                )
                if imported is not None:
                    resources.append(imported)
                    await self.store.attach_resource(pending.checkpoint, change, imported)
            output.source_item_id = object_identity
            if change.occurred_at is not None:
                output.occurred_at = change.occurred_at
            source_metadata = {
                "source_connection_id": connection.connection_id,
                "source_plugin_id": connection.plugin_id,
                "source_id": source.source_id,
                "source_object_id": change.object_id,
                "source_object_version": change.version,
                "source_evidence_ref": evidence.model_dump(mode="json"),
                "source_resource_refs": [ref.model_dump(mode="json") for ref in resources],
                "projection_rule_revision": rule_revision,
            }
            # Host identity overrides all plugin-provided identity-like metadata.
            output.domain_payload.update(source_metadata)
            output.provenance.update(dict(provenance or {}))
            output.provenance.update(source_metadata)
            result = await self.gateway.ingest(
                source, output, metadata,
                allowed_edge_whitelist=allowed_edge_whitelist,
                boundary=boundary,
                allow_pre_clear_events=allow_pre_clear_events,
                host_idempotency_key=evidence.resource_id,
            )
            if result.stats.get("skip_reason") == "memory_clear_epoch_changed":
                raise SourceCheckpointConflict("Memory was cleared during source ingestion")
            if not result.ingested:
                raise RuntimeError("Source revision memory ingestion was not confirmed")
            await self.store.record_receipt(
                pending, change, event_id=result.event_id, outcome=str(result.stats.get("memory_outcome") or ""),
            )
        return await self.store.accept_batch(connection, pending)

    async def _import_output_resource(
        self, *, connection: PluginConnection, source: Source, raw_ref: str, declared: list[Any]
    ) -> tuple[str, Any | None]:
        for ref in declared:
            if ref.resource_id == raw_ref:
                await self.store.read_resource(connection, ref)
                return raw_ref, None
        root = source.context.resources_dir.resolve()
        candidate = Path(raw_ref)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise PermissionError("Source resource must be inside its host-allocated resource directory")
        content = await asyncio.to_thread(_read_scoped_resource, root, resolved.relative_to(root))
        ref = await self.store.register_resource(
            connection, content,
            media_type=mimetypes.guess_type(resolved.name)[0] or "application/octet-stream",
            display_name=resolved.name,
        )
        return ref.resource_id, ref


def _read_scoped_resource(root: Path, relative_path: Path) -> bytes:
    """Traverse private resource directories without following replaceable links."""
    limit = 16 * 1024 * 1024
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise PermissionError("Source resource path escapes its connection")
    if os.name == "nt":
        return _read_windows_scoped_resource(root, relative_path, limit)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative_path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(relative_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise PermissionError("Source resource must be a regular file")
            if info.st_size > limit:
                raise ValueError("Source resource exceeds the host size limit")
            chunks = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if remaining == 0:
                raise ValueError("Source resource exceeds the host size limit")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def _read_windows_scoped_resource(root: Path, relative_path: Path, limit: int) -> bytes:
    """Lock directory handles against replacement and reject Windows reparse points."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    attributes = kernel.GetFileInformationByHandleEx
    attributes.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    attributes.restype = wintypes.BOOL
    read = kernel.ReadFile
    read.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    read.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handles = []
    try:
        paths = [root]
        for part in relative_path.parts:
            paths.append(paths[-1] / part)
        for index, path in enumerate(paths):
            directory = index < len(paths) - 1
            # OPEN_REPARSE_POINT plus a handle without FILE_SHARE_DELETE prevents
            # path substitution while the following child is opened.
            handle = create(str(path), 0x80 if directory else 0x80000000, 3 if directory else 1,
                            None, 3, 0x00200000 | (0x02000000 if directory else 0), None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = (wintypes.DWORD * 2)()
            if not attributes(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info[0] & 0x400 or bool(info[0] & 0x10) != directory:
                raise PermissionError("Source resource traversal contains a reparse point or non-file")
        chunks = []
        remaining = limit + 1
        while remaining:
            buffer = ctypes.create_string_buffer(min(65536, remaining))
            length = wintypes.DWORD()
            if not read(handles[-1], buffer, len(buffer), ctypes.byref(length), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if length.value == 0:
                break
            chunks.append(buffer.raw[:length.value])
            remaining -= length.value
        if remaining == 0:
            raise ValueError("Source resource exceeds the host size limit")
        return b"".join(chunks)
    finally:
        for handle in reversed(handles):
            close(handle)


__all__ = ["SourceBatchIngestor"]
