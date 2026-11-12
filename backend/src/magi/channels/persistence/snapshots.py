"""Logical row mapping for explicit offline SQLite channel transfers."""

from __future__ import annotations

from ...core.sqlite import sqlite_connection_async
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
