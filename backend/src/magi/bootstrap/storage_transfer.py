"""Offline logical cutover through the same plugin contracts used at runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from magi_plugin_sdk.fs import read_managed_bytes
from magi_plugin_sdk.storage import StorageDomain
from ..config.storage_models import StorageSelection
from ..db.logical_transfer import cutover_logical_state
from ..db.storage_bindings import StorageBinding
from ..utils.runtime import RuntimePaths
from ..utils.worker_instance import WorkerInstance
from .storage_plugins import build_storage_plugin_runtime, read_storage_settings
from .storage_selection import BINDING_PATHS, binding_file, open_storage, resolve_storage


async def migrate_storage(paths: RuntimePaths, domain: StorageDomain, *, replace_destination: bool = False) -> dict[str, str]:
    runtime = build_storage_plugin_runtime(paths)
    sessions = []
    try:
        file = binding_file(paths, domain)
        binding = file.read_or_create()
        destination_entry, destination = await resolve_storage(runtime, getattr(read_storage_settings(paths), domain), domain)
        source_selection = (StorageSelection(connection_id=binding.active.connection_id, provider_id=binding.active.kind)
                            if binding.active is not None else StorageSelection())
        source_entry, source = await resolve_storage(runtime, source_selection, domain)
        if binding.active is not None and source != binding.active:
            raise ValueError("The original source connection no longer identifies the active storage owner")
        reader = await open_storage(source_entry, source, domain, binding.center_id, migrate=True, maintenance=True)
        sessions.append(reader)
        if source == destination:
            if binding.pending is not None:
                raise RuntimeError("Resume the pending destination before selecting the source")
            await reader.transfer.export_state()
            binding.active = source
            file.write(binding)
            return {"status": "unchanged", "storage": source.kind}
        writer = await open_storage(destination_entry, destination, domain, binding.center_id, migrate=True, maintenance=True)
        sessions.append(writer)
        return await cutover_logical_state(binding_file=file, destination=destination,
            reader=reader.transfer, writer=writer.transfer, replace_destination=replace_destination)
    finally:
        try:
            for session in reversed(sessions):
                await session.close()
        finally:
            await runtime.close()


async def adopt_current_binding(paths: RuntimePaths, domain: StorageDomain) -> dict[str, str]:
    """Upgrade pre-plugin metadata offline only after proving the same physical owner."""
    payload = read_managed_bytes(paths.data_dir / BINDING_PATHS[domain], max_bytes=16384)
    raw = json.loads(payload) if payload else None
    if not isinstance(raw, dict) or raw.get("version") != 1 or raw.get("pending") is not None:
        raise ValueError("Adoption requires a settled version-1 binding; pending transfers must finish first")
    if set(raw) != {"version", "center_id", "active", "pending"} or not isinstance(raw.get("active"), dict):
        raise ValueError("The old binding has no exact active owner")
    runtime = build_storage_plugin_runtime(paths)
    selected = None
    try:
        entry, target = await resolve_storage(runtime, getattr(read_storage_settings(paths), domain), domain)
        old = raw["active"]
        local_ids = {"channels": "local-channels-v1", "memory_events": "local-l1-events-v1", "chat": "local-chat-v1"}
        expected = ({"kind": "sqlite", "identity": local_ids[domain]} if target.plugin_id == "storage-sqlite"
                    else {"kind": target.kind, "identity": target.identity})
        if old != expected:
            raise ValueError("The selected connection is not the same physical storage owner")
        binding = StorageBinding(center_id=raw["center_id"], active=target)
        selected = await open_storage(entry, target, domain, binding.center_id, migrate=False, maintenance=True)
        await selected.transfer.export_state()
        binding_file(paths, domain).write(binding)
        return {"status": "adopted", "storage": target.kind}
    finally:
        try:
            if selected is not None:
                await selected.close()
        finally:
            await runtime.close()


def main(domain: StorageDomain | None = None) -> None:
    parser = argparse.ArgumentParser(description="Transfer the selected storage domain while its Magi service is stopped")
    parser.add_argument("--root", type=Path, required=True)
    if domain is None:
        parser.add_argument("--domain", choices=("chat", "memory_events", "channels"), required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--replace-target", action="store_true", help="Replace the owned destination in one transaction")
    action.add_argument("--adopt-current-binding", action="store_true", help="Upgrade metadata for the same pre-plugin database")
    args = parser.parse_args()
    root = args.root.expanduser().absolute()
    with WorkerInstance(root):
        os.environ["MAGI_HOME"] = str(root)
        paths = RuntimePaths(base_dir=root)
        selected_domain = domain or args.domain
        operation = (adopt_current_binding(paths, selected_domain) if args.adopt_current_binding
                     else migrate_storage(paths, selected_domain, replace_destination=args.replace_target))
        print(json.dumps(asyncio.run(operation), sort_keys=True))


if __name__ == "__main__":
    main()
