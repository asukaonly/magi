"""Offline logical chat cutover and startup selection fencing."""

from typing import Literal

from ..chat.storage.mysql.database import MysqlChatDatabase
from ..chat.storage.snapshots import RelationalChatStateTransfer
from ..chat.storage.sqlite_database import SqliteChatDatabase
from ..db.identities import identity_key
from ..db.logical_transfer import cutover_logical_state
from ..db.mysql import MysqlDatabase, MysqlSettings
from ..db.mysql_migrations import upgrade_mysql_chat
from ..db.runner import run_upgrade_database
from ..db.storage_bindings import StorageBinding, StorageBindingFile, StorageTarget
from ..utils.runtime import RuntimePaths

StorageKind = Literal["sqlite", "mysql"]


def binding_file(paths: RuntimePaths) -> StorageBindingFile:
    return StorageBindingFile(paths.data_dir / "chat" / "storage-binding.json")


def storage_target(kind: StorageKind, mysql: MysqlSettings | None = None) -> StorageTarget:
    if kind == "sqlite":
        return StorageTarget(kind="sqlite", identity="local-chat-v1")
    if mysql is None:
        raise ValueError("MySQL settings are required for chat storage")
    return StorageTarget(kind="mysql", identity=identity_key(mysql.host.lower(), str(mysql.port), mysql.database))


async def preflight_storage_selection(paths: RuntimePaths, kind: StorageKind, mysql: MysqlSettings | None) -> StorageBinding:
    binding = binding_file(paths).read_or_create()
    target = storage_target(kind, mysql)
    if binding.pending is not None:
        raise RuntimeError("Chat storage migration is incomplete; resume offline migration before startup")
    if binding.active is not None and binding.active != target:
        raise RuntimeError("Chat storage changed; run offline chat storage migration before startup")
    if binding.active is None and kind == "mysql" and paths.chat_db_path.exists():
        local = await RelationalChatStateTransfer(SqliteChatDatabase(paths.chat_db_path)).export_state()
        if not local.is_empty():
            raise RuntimeError("Local chat data exists; migrate it before enabling MySQL")
    return binding


async def migrate_chat_storage(
    paths: RuntimePaths,
    *,
    destination: StorageKind,
    mysql: MysqlSettings | None = None,
    source_mysql: MysqlSettings | None = None,
    replace_destination: bool = False,
) -> dict[str, str]:
    """Caller holds the offline worker lease; source data remains untouched."""
    file = binding_file(paths)
    binding = file.read_or_create()
    target = storage_target(destination, mysql)
    source = binding.active or storage_target("sqlite")
    if source == target:
        if binding.pending is not None:
            raise RuntimeError("Pending chat destination differs from the requested transfer")
        return {"status": "unchanged", "storage": destination}
    if source.kind == "sqlite" or destination == "sqlite":
        run_upgrade_database("chat", paths.chat_db_path)
    local = RelationalChatStateTransfer(SqliteChatDatabase(paths.chat_db_path))
    databases: list[MysqlDatabase] = []

    async def native(settings: MysqlSettings) -> RelationalChatStateTransfer:
        database = MysqlDatabase(settings)
        databases.append(database)
        await upgrade_mysql_chat(database)
        adapter = MysqlChatDatabase(database, center_id=binding.center_id)
        await adapter.initialize()
        return RelationalChatStateTransfer(adapter)

    try:
        reader = local
        writer = local
        if source.kind == "mysql":
            source_settings = source_mysql or mysql
            if source_settings is None or storage_target("mysql", source_settings) != source:
                raise ValueError("Source MySQL settings do not identify the active chat store")
            reader = await native(source_settings)
        if destination == "mysql":
            if mysql is None:
                raise ValueError("Destination MySQL settings are required")
            writer = await native(mysql)
        return await cutover_logical_state(
            binding_file=file, destination=target, reader=reader, writer=writer,
            replace_destination=replace_destination,
        )
    finally:
        for database in reversed(databases):
            await database.close()
