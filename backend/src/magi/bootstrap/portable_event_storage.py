"""Open an exact plugin event owner for backup and journaled restore."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ..config.storage_models import StructuredStorageSettings
from ..db.storage_bindings import StorageTarget
from ..memory.l1.storage_snapshot import EventStateTransfer
from ..utils.runtime import RuntimePaths
from .storage_plugins import build_storage_plugin_runtime, read_storage_settings
from .storage_selection import binding_file, resolve_storage, open_storage


@dataclass(frozen=True, slots=True)
class PortableEventStorage:
    transfer: EventStateTransfer
    target: StorageTarget
    center_id: str


@asynccontextmanager
async def open_portable_event_storage(paths: RuntimePaths, *, settings: StructuredStorageSettings | None = None) -> AsyncIterator[PortableEventStorage]:
    settings = settings if settings is not None else read_storage_settings(paths)
    runtime = build_storage_plugin_runtime(paths)
    selected = None
    try:
        binding = binding_file(paths, "memory_events").read_or_create()
        entry, target = await resolve_storage(runtime, settings.memory_events, "memory_events")
        if binding.pending is not None or (binding.active is not None and binding.active != target):
            raise RuntimeError("Event storage configuration does not match the active owner")
        if target.plugin_id != "storage-sqlite" and binding.active != target:
            raise RuntimeError("External event storage must be initialized before maintenance")
        selected = await open_storage(entry, target, "memory_events", binding.center_id, migrate=False, maintenance=True)
        yield PortableEventStorage(selected.transfer, target, binding.center_id)
    finally:
        try:
            if selected is not None:
                await selected.close()
        finally:
            await runtime.close()
