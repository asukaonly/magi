"""Open the selected event owner for maintenance outside runtime pool lifetime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import yaml
from magi_plugin_sdk.fs import read_managed_bytes

from ..config.storage_models import StructuredStorageSettings
from ..db.mysql import MysqlDatabase
from ..db.storage_bindings import StorageTarget
from ..memory.l1.storage.mysql.snapshots import MysqlEventStateTransfer
from ..memory.l1.storage.snapshots import SqliteEventStateTransfer
from ..memory.l1.storage_snapshot import EventStateTransfer
from ..utils.runtime import RuntimePaths
from .event_storage import binding_file, storage_target


@dataclass(frozen=True, slots=True)
class PortableEventStorage:
    transfer: EventStateTransfer
    target: StorageTarget
    center_id: str


def read_storage_settings(paths: RuntimePaths) -> StructuredStorageSettings:
    payload = read_managed_bytes(paths.base_dir / "config" / "agent.yaml", max_bytes=4 * 1024 * 1024)
    raw = yaml.safe_load(payload) if payload is not None else {}
    if not isinstance(raw, dict):
        raise ValueError("Agent configuration must be a mapping")
    return StructuredStorageSettings.model_validate(raw.get("structured_storage", {}))


@asynccontextmanager
async def open_portable_event_storage(
    paths: RuntimePaths, *, settings: StructuredStorageSettings | None = None,
) -> AsyncIterator[PortableEventStorage]:
    """Require the active binding; never migrate or change the selected owner here."""
    settings = settings if settings is not None else read_storage_settings(paths)
    binding = binding_file(paths).read_or_create()
    target = storage_target(settings.memory_events, settings.mysql)
    if binding.pending is not None or (binding.active is not None and binding.active != target):
        raise RuntimeError("Event storage configuration does not match the active owner")
    if target.kind == "sqlite":
        yield PortableEventStorage(
            SqliteEventStateTransfer(str(paths.l1_memory_db_path)), target, binding.center_id,
        )
        return
    if binding.active != target or settings.mysql is None:
        raise RuntimeError("External event storage must be initialized before maintenance")
    database = MysqlDatabase(settings.mysql)
    try:
        transfer = MysqlEventStateTransfer(database, center_id=binding.center_id)
        await transfer.initialize()
        yield PortableEventStorage(transfer, target, binding.center_id)
    finally:
        await database.close()
