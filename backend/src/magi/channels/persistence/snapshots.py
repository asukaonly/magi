"""Logical row mapping for explicit offline SQLite/MySQL channel transfers."""

from __future__ import annotations
from uuid import uuid4
from sqlalchemy import text

from ...core.sqlite import sqlite_connection_async
from ...db.identities import identity_key
from ...db.mysql import MysqlDatabase
from ..storage_snapshot import (
    ChannelStorageSnapshot,
    SessionBindingRecord,
    NotificationCursorRecord,
    RelayCursorRecord,
    BindingSettingsRecord,
    DeliveryReceiptRecord,
    OutreachIntentRecord,
    OutreachReceiptRecord,
)

# The shared database lifecycle includes proactive delivery. Every field in the
# wire snapshot is a logical value; derived MySQL index keys are rebuilt on import.
_COLLECTIONS = (
    ("bindings", "channel_session_mappings", SessionBindingRecord),
    ("notification_cursors", "channel_notification_cursors", NotificationCursorRecord),
    ("relay_cursors", "channel_relay_state", RelayCursorRecord),
    ("binding_settings", "channel_binding_settings", BindingSettingsRecord),
    ("delivery_receipts", "delivery_receipts", DeliveryReceiptRecord),
    ("outreach_intents", "outreach_outbox", OutreachIntentRecord),
    ("outreach_receipts", "outreach_delivery_log", OutreachReceiptRecord),
)


class SqliteChannelStateTransfer:
    def __init__(self, path: str) -> None:
        self._path = path

    async def export_state(self) -> ChannelStorageSnapshot:
        payload = {}
        async with sqlite_connection_async(self._path) as db:
            await db.execute("BEGIN")
            for name, table, model in _COLLECTIONS:
                columns = ",".join(model.model_fields)
                rows = await db.execute_fetchall(f"SELECT {columns} FROM {table}")
                payload[name] = [model.model_validate(dict(row)) for row in rows]
        return ChannelStorageSnapshot.model_validate(payload)

    async def import_state(
        self, snapshot: ChannelStorageSnapshot, *, replace: bool = False
    ) -> None:
        async with sqlite_connection_async(self._path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            for _, table, _ in _COLLECTIONS:
                if replace:
                    await db.execute(f"DELETE FROM {table}")
                elif await db.execute_fetchall(f"SELECT 1 FROM {table} LIMIT 1"):
                    raise ValueError("Channel migration destination is not empty")
            for name, table, model in _COLLECTIONS:
                columns = list(model.model_fields)
                rows = [record.model_dump() for record in getattr(snapshot, name)]
                if rows:
                    await db.executemany(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        [tuple(row[column] for column in columns) for row in rows],
                    )
            await db.commit()


class MysqlChannelStateTransfer:
    def __init__(self, database: MysqlDatabase) -> None:
        self._database = database

    async def export_state(self) -> ChannelStorageSnapshot:
        payload = {}
        async with self._database.transaction() as db:
            for name, table, model in _COLLECTIONS:
                columns = ",".join(model.model_fields)
                rows = (await db.execute(text(f"SELECT {columns} FROM {table}"))).mappings().all()
                payload[name] = [model.model_validate(dict(row)) for row in rows]
        return ChannelStorageSnapshot.model_validate(payload)

    async def import_state(
        self, snapshot: ChannelStorageSnapshot, *, replace: bool = False
    ) -> None:
        async with self._database.transaction() as db:
            for _, table, _ in _COLLECTIONS:
                if replace:
                    await db.execute(text(f"DELETE FROM {table}"))
                elif (
                    await db.execute(text(f"SELECT 1 FROM {table} LIMIT 1 FOR UPDATE"))
                ).first() is not None:
                    raise ValueError("Channel migration destination is not empty")
            for name, table, _ in _COLLECTIONS:
                for record in getattr(snapshot, name):
                    values = record.model_dump()
                    if name == "bindings":
                        values["identity_key"] = identity_key(
                            record.channel_type, record.external_chat_id, record.external_thread_id
                        )
                        values["session_key"] = identity_key(record.magi_session_id)
                    elif name == "notification_cursors":
                        values["identity_key"] = identity_key(
                            record.channel_type, record.external_chat_id
                        )
                    elif name == "relay_cursors":
                        values["identity_key"] = identity_key(record.state_key)
                    elif name == "binding_settings":
                        values["identity_key"] = identity_key(
                            record.channel_type, record.external_user_id
                        )
                    elif name == "delivery_receipts":
                        values["session_key"] = identity_key(record.session_id)
                        values["run_key"] = identity_key(record.run_id)
                    elif name == "outreach_intents":
                        values["identity_key"] = identity_key(
                            record.correlation_id, record.channel_scope
                        )
                        values["creation_token"] = uuid4().hex
                    else:
                        values["identity_key"] = identity_key(
                            record.correlation_id, record.channel_type
                        )
                        values["user_key"] = identity_key(record.user_id)
                    columns = list(values)
                    await db.execute(
                        text(
                            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(':' + column for column in columns)})"
                        ),
                        values,
                    )
