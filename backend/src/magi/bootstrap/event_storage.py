"""Compose and cut over the complete L1 event owner without guessing its source."""

from __future__ import annotations

from typing import Literal

from ..db.identities import identity_key
from ..db.logical_transfer import cutover_logical_state
from ..db.mysql import MysqlDatabase, MysqlSettings
from ..db.mysql_migrations import upgrade_mysql_l1
from ..db.storage_bindings import StorageBinding, StorageBindingFile, StorageTarget
from ..memory.l1.ports import MemoryEventRepository
from ..memory.l1.storage.events import SqliteMemoryEventRepository
from ..memory.l1.storage.snapshots import SqliteEventStateTransfer
from ..memory.l1.storage.mysql.events import MysqlMemoryEventRepository
from ..memory.l1.storage.mysql.snapshots import MysqlEventStateTransfer
from ..utils.runtime import RuntimePaths

StorageKind = Literal["sqlite", "mysql"]


def binding_file(paths: RuntimePaths) -> StorageBindingFile:
    return StorageBindingFile(paths.data_dir / "memory" / "event-storage-binding.json")


def storage_target(kind: StorageKind, mysql: MysqlSettings | None = None) -> StorageTarget:
    if kind == "sqlite":
        return StorageTarget(kind="sqlite", identity="local-l1-events-v1")
    if mysql is None:
        raise ValueError("MySQL settings are required for event storage")
    return StorageTarget(
        kind="mysql", identity=identity_key(mysql.host.lower(), str(mysql.port), mysql.database)
    )


async def preflight_storage_selection(
    paths: RuntimePaths, kind: StorageKind, mysql: MysqlSettings | None
) -> StorageBinding:
    binding = binding_file(paths).read_or_create()
    target = storage_target(kind, mysql)
    if binding.pending is not None:
        raise RuntimeError(
            "Event storage migration is incomplete; resume offline migration before startup"
        )
    if binding.active is not None and binding.active != target:
        raise RuntimeError(
            "Event storage changed; run offline event storage migration before startup"
        )
    if binding.active is None and kind == "mysql":
        local = await SqliteEventStateTransfer(str(paths.l1_memory_db_path)).export_state()
        if not local.is_empty():
            raise RuntimeError("Local memory events exist; migrate them before enabling MySQL")
    return binding


async def compose_event_repository(
    paths: RuntimePaths,
    kind: StorageKind,
    mysql: MysqlSettings | None,
    database: MysqlDatabase | None,
) -> MemoryEventRepository:
    binding = await preflight_storage_selection(paths, kind, mysql)
    if kind == "sqlite":
        repository = SqliteMemoryEventRepository(str(paths.l1_memory_db_path))
    else:
        if database is None:
            raise RuntimeError("MySQL event storage requires a managed connection")
        await upgrade_mysql_l1(database)
        repository = MysqlMemoryEventRepository(database, center_id=binding.center_id)
    await repository.initialize()
    binding.active = storage_target(kind, mysql)
    binding_file(paths).write(binding)
    return repository


async def migrate_event_storage(
    paths: RuntimePaths,
    *,
    destination: StorageKind,
    mysql: MysqlSettings | None = None,
    source_mysql: MysqlSettings | None = None,
    replace_destination: bool = False,
) -> dict[str, str]:
    """Caller holds the offline lease; support local/remote and explicit remote-to-remote moves."""
    file = binding_file(paths)
    binding = file.read_or_create()
    target = storage_target(destination, mysql)
    source = binding.active or storage_target("sqlite")
    if source == target:
        if binding.pending is not None:
            raise RuntimeError("Pending event destination differs from the requested transfer")
        return {"status": "unchanged", "storage": destination}
    local = SqliteEventStateTransfer(str(paths.l1_memory_db_path))
    databases = []
    try:
        reader = local
        writer = local
        if source.kind == "mysql":
            source_settings = source_mysql or mysql
            if source_settings is None or storage_target("mysql", source_settings) != source:
                raise ValueError("Source MySQL settings do not identify the active event store")
            source_database = MysqlDatabase(source_settings)
            databases.append(source_database)
            await upgrade_mysql_l1(source_database)
            reader = MysqlEventStateTransfer(source_database, center_id=binding.center_id)
            await reader.initialize()
        if destination == "mysql":
            if mysql is None:
                raise ValueError("Destination MySQL settings are required")
            target_database = MysqlDatabase(mysql)
            databases.append(target_database)
            await upgrade_mysql_l1(target_database)
            writer = MysqlEventStateTransfer(target_database, center_id=binding.center_id)
            await writer.initialize()
        return await cutover_logical_state(
            binding_file=file,
            destination=target,
            reader=reader,
            writer=writer,
            replace_destination=replace_destination,
        )
    finally:
        for database in reversed(databases):
            await database.close()
