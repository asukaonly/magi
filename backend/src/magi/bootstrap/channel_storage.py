"""Compose and transfer the complete channel persistence lifecycle scope."""

from __future__ import annotations
import hashlib
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from ..channels.persistence.snapshots import SqliteChannelStateTransfer, MysqlChannelStateTransfer
from ..channels.storage_snapshot import ChannelStateTransfer, ChannelStorageSnapshot
from ..config.storage_models import StructuredStorageSettings
from ..db.identities import identity_key
from ..db.mysql import MysqlDatabase
from ..db.mysql_migrations import upgrade_mysql_channels
from ..db.storage_bindings import StorageBinding, StorageBindingFile, StorageTarget, StorageTransferIntent
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


def snapshot_digest(snapshot: ChannelStorageSnapshot) -> str:
    payload = snapshot.model_dump(mode="json")
    for name, records in payload.items():
        if isinstance(records, list):
            records.sort(key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


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
        snapshot = await reader.export_state()
        digest = snapshot_digest(snapshot)
        intent = StorageTransferIntent(
            destination=destination, snapshot_digest=digest, replace_destination=replace_destination
        )
        if binding.pending is not None and binding.pending != intent:
            raise RuntimeError(
                "Resume the original storage transfer before requesting a different cutover"
            )
        target_snapshot = await writer.export_state()
        if (
            snapshot_digest(target_snapshot) != digest
            and not target_snapshot.is_empty()
            and not replace_destination
        ):
            raise ValueError(
                "Destination has data; explicitly replace it or choose an empty destination"
            )
        binding.pending = intent
        file.write(binding)
        if snapshot_digest(target_snapshot) != digest:
            await writer.import_state(snapshot, replace=replace_destination)
        if snapshot_digest(await writer.export_state()) != digest:
            raise RuntimeError("Channel storage verification failed; source remains active")
        binding.active = destination
        binding.pending = None
        file.write(binding)
        return {"status": "migrated", "storage": destination.kind, "digest": digest}
