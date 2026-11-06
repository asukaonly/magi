"""Resolve durable repository owners before opening selected plugin sessions."""

from __future__ import annotations

from dataclasses import dataclass
from magi_plugin_sdk.storage import StorageDomain, StorageOpen, StorageOpened
from magi_plugin_sdk.storage_models.channels import ChannelStorageSnapshot
from magi_plugin_sdk.storage_models.event_snapshot import EventStorageSnapshot
from magi_plugin_sdk.storage_models.chat_snapshot import ChatStorageSnapshot

from ..config.storage_models import StorageSelection
from ..db.storage_bindings import StorageBinding, StorageBindingFile, StorageTarget
from ..db.storage_transfer_proxy import StorageTransferProxy
from ..plugins.storage_registry import StorageContribution
from ..plugins.storage_runtime import StoragePluginRuntime
from ..utils.runtime import RuntimePaths

SNAPSHOTS = {"channels": ChannelStorageSnapshot, "memory_events": EventStorageSnapshot, "chat": ChatStorageSnapshot}
BINDING_PATHS = {"channels": "channels/storage-binding.json", "memory_events": "memory/event-storage-binding.json", "chat": "chat/storage-binding.json"}


def binding_file(paths: RuntimePaths, domain: StorageDomain) -> StorageBindingFile:
    return StorageBindingFile(paths.data_dir / BINDING_PATHS[domain])


async def resolve_storage(runtime: StoragePluginRuntime, selection: StorageSelection, domain: StorageDomain) -> tuple[StorageContribution, StorageTarget]:
    connection_id = selection.connection_id or runtime.default_sqlite_connection()
    entry = await runtime.load(connection_id, selection.provider_id, domain)
    return entry, StorageTarget(kind=entry.spec.provider_id, identity=entry.spec.target_identity,
                               plugin_id=entry.plugin_id, connection_id=connection_id, contract_version=entry.spec.contract_version)


@dataclass
class OpenStorage:
    entry: StorageContribution
    target: StorageTarget
    opened: StorageOpened
    transfer: StorageTransferProxy

    async def close(self) -> None:
        await self.entry.provider.close(self.opened.session_id)


async def open_storage(entry: StorageContribution, target: StorageTarget, domain: StorageDomain,
                       center_id: str, *, migrate: bool, maintenance: bool = False) -> OpenStorage:
    opened = await entry.provider.open(StorageOpen(domain=domain, center_id=center_id,
        mode="maintenance" if maintenance else "runtime", migrate=migrate))
    if opened.target_identity != target.identity:
        await entry.provider.close(opened.session_id)
        raise RuntimeError("Storage provider identity changed while opening its session")
    return OpenStorage(entry, target, opened, StorageTransferProxy(entry.provider, opened.session_id, SNAPSHOTS[domain]))


async def preflight_storage(paths: RuntimePaths, runtime: StoragePluginRuntime, domain: StorageDomain,
                            entry: StorageContribution, target: StorageTarget) -> StorageBinding:
    binding = binding_file(paths, domain).read_or_create()
    if binding.pending is not None:
        raise RuntimeError("Storage transfer is incomplete; resume offline maintenance before startup")
    if binding.active is not None and binding.active != target:
        raise RuntimeError("Storage selection changed; transfer or adopt the exact owner offline before startup")
    if binding.active is None and entry.plugin_id != "storage-sqlite":
        path = {"channels": paths.channels_db_path, "memory_events": paths.l1_memory_db_path, "chat": paths.chat_db_path}[domain]
        if path.exists():
            local_entry, local_target = await resolve_storage(runtime, StorageSelection(), domain)
            local = await open_storage(local_entry, local_target, domain, binding.center_id, migrate=False, maintenance=True)
            try:
                if not (await local.transfer.export_state()).is_empty():
                    raise RuntimeError("Local data exists; transfer it before selecting external storage")
            finally:
                await local.close()
    return binding
