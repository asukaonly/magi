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


def main() -> None:
    """Transfer the configured chat scope while holding the center lease."""
    import argparse
    import asyncio
    import json
    from pathlib import Path

    import yaml
    from magi_plugin_sdk.fs import read_managed_bytes

    from ..config.storage_models import StructuredStorageSettings
    from ..utils.worker_instance import WorkerInstance

    parser = argparse.ArgumentParser(description="Migrate chat while the Magi center is stopped")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--target", choices=("sqlite", "mysql"), required=True)
    parser.add_argument("--replace-target", action="store_true",
        help="Replace complete chat state in the owned destination")
    parser.add_argument("--source-mysql-config", type=Path,
        help="Original MySQL settings for a remote-to-remote move")
    arguments = parser.parse_args()
    root = arguments.root.expanduser().absolute()
    with WorkerInstance(root):
        raw = yaml.safe_load(read_managed_bytes(root / "config" / "agent.yaml", max_bytes=4 * 1024 * 1024))
        if not isinstance(raw, dict):
            raise ValueError("Agent configuration must be a mapping")
        settings = StructuredStorageSettings.model_validate(raw.get("structured_storage", {}))
        if settings.chat != arguments.target:
            raise ValueError("Configure the requested chat storage target before running migration")
        source_mysql = None
        if arguments.source_mysql_config is not None:
            source_mysql = MysqlSettings.model_validate(yaml.safe_load(read_managed_bytes(
                arguments.source_mysql_config.expanduser().absolute(), max_bytes=1024 * 1024
            )))
        result = asyncio.run(migrate_chat_storage(
            RuntimePaths(base_dir=root), destination=arguments.target,
            mysql=settings.mysql, source_mysql=source_mysql,
            replace_destination=arguments.replace_target,
        ))
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
