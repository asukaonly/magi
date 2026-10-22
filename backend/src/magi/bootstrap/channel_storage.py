"""Compose and transfer the complete channel persistence lifecycle scope."""

from __future__ import annotations
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from ..channels.persistence.snapshots import SqliteChannelStateTransfer, MysqlChannelStateTransfer
from ..channels.storage_snapshot import ChannelStateTransfer
from ..config.storage_models import StructuredStorageSettings
from ..db.identities import identity_key
from ..db.logical_transfer import cutover_logical_state
from ..db.mysql import MysqlDatabase
from ..db.mysql_migrations import upgrade_mysql_channels
from ..db.storage_bindings import StorageBinding, StorageBindingFile, StorageTarget
from ..utils.runtime import RuntimePaths


def binding_file(paths: RuntimePaths) -> StorageBindingFile:
    return StorageBindingFile(paths.data_dir / "channels" / "storage-binding.json")


def sqlite_target(paths: RuntimePaths) -> StorageTarget:
    return StorageTarget(kind="sqlite", identity="local-channels-v1")


def configured_target(paths: RuntimePaths, settings: StructuredStorageSettings) -> StorageTarget:
    if settings.channels == "sqlite":
        return sqlite_target(paths)
    mysql = settings.mysql
    if mysql is None:
        raise ValueError("MySQL settings are required")
    return StorageTarget(
        kind="mysql", identity=identity_key(mysql.host.lower(), str(mysql.port), mysql.database)
    )


async def claim_mysql_owner(database: MysqlDatabase, center_id: str) -> None:
    async with database.transaction() as db:
        current = (
            await db.execute(
                text("SELECT center_id FROM magi_channels_owner WHERE singleton_id=1 FOR UPDATE")
            )
        ).scalar_one_or_none()
        if current is not None:
            if current != center_id:
                raise RuntimeError("MySQL channel storage belongs to another logical center")
            return
        for table in (
            "channel_session_mappings",
            "channel_notification_cursors",
            "channel_relay_state",
            "channel_binding_settings",
            "delivery_receipts",
            "outreach_outbox",
            "outreach_delivery_log",
        ):
            if (await db.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))).first() is not None:
                raise RuntimeError("Unowned MySQL channel storage is not empty")
        await db.execute(
            text("INSERT INTO magi_channels_owner(singleton_id,center_id) VALUES (1,:center)"),
            {"center": center_id},
        )


async def preflight_storage_selection(
    paths: RuntimePaths, settings: StructuredStorageSettings
) -> StorageBinding:
    file = binding_file(paths)
    binding = file.read_or_create()
    target = configured_target(paths, settings)
    if binding.pending is not None:
        raise RuntimeError(
            "Channel storage migration is incomplete; resume offline migration before startup"
        )
    if binding.active is not None and binding.active != target:
        raise RuntimeError(
            "Channel storage changed; run offline channel storage migration before startup"
        )
    if binding.active is None and target.kind == "mysql":
        existing = await SqliteChannelStateTransfer(str(paths.channels_db_path)).export_state()
        if not existing.is_empty():
            raise RuntimeError("Local channel data exists; migrate it before enabling MySQL")
    return binding


async def verify_storage_selection(
    paths: RuntimePaths, settings: StructuredStorageSettings, database: MysqlDatabase | None
) -> None:
    binding = await preflight_storage_selection(paths, settings)
    target = configured_target(paths, settings)
    if target.kind == "mysql":
        if database is None:
            raise RuntimeError("MySQL storage owner cannot be verified without a connection")
        await claim_mysql_owner(database, binding.center_id)
    binding.active = target
    binding_file(paths).write(binding)


@asynccontextmanager
async def transfer_adapters(
    paths: RuntimePaths, settings: StructuredStorageSettings, *, needs_mysql: bool
) -> AsyncIterator[tuple[ChannelStateTransfer, ChannelStateTransfer | None]]:
    sqlite = SqliteChannelStateTransfer(str(paths.channels_db_path))
    database = None
    try:
        remote = None
        if needs_mysql:
            if settings.mysql is None:
                raise ValueError("MySQL settings are required for this transfer")
            database = MysqlDatabase(settings.mysql)
            await upgrade_mysql_channels(database)
            await claim_mysql_owner(database, binding_file(paths).read_or_create().center_id)
            remote = MysqlChannelStateTransfer(database)
        yield sqlite, remote
    finally:
        if database is not None:
            await database.close()


async def migrate_channel_storage(
    paths: RuntimePaths, settings: StructuredStorageSettings, *, replace_destination: bool = False
) -> dict[str, str]:
    """Transfer while the caller owns an offline runtime lease; never replay effects."""
    file = binding_file(paths)
    binding = file.read_or_create()
    destination = configured_target(paths, settings)
    source = binding.active or sqlite_target(paths)
    if source == destination:
        if binding.pending is not None:
            raise RuntimeError("Pending storage destination does not match the requested transfer")
        return {"status": "unchanged", "storage": destination.kind}
    if source.kind == destination.kind:
        raise ValueError("Changing MySQL servers requires a separate source configuration")
    async with transfer_adapters(paths, settings, needs_mysql=True) as (local, remote):
        if remote is None:
            raise RuntimeError("MySQL transfer adapter is unavailable")
        remote_target = configured_target(paths, settings.model_copy(update={"channels": "mysql"}))
        if source.kind == "mysql" and source != remote_target:
            raise ValueError("MySQL settings do not identify the currently active source")
        reader = local if source.kind == "sqlite" else remote
        writer = local if destination.kind == "sqlite" else remote
        return await cutover_logical_state(
            binding_file=file,
            destination=destination,
            reader=reader,
            writer=writer,
            replace_destination=replace_destination,
        )
