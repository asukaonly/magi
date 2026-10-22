"""MySQL implementations of channel persistence ports."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Mapping

from sqlalchemy import text
from magi_plugin_sdk.delivery import DeliveryReceipt

from ...db.mysql import MysqlDatabase
from ...db.identities import identity_key
from ..contracts import ChannelSessionMapping
from ..contracts import ChannelBindingSettings


def _mapping(row: Mapping[str, Any]) -> ChannelSessionMapping:
    return ChannelSessionMapping(
        channel_type=str(row["channel_type"]),
        external_chat_id=str(row["external_chat_id"]),
        external_thread_id=str(row["external_thread_id"]) or None,
        magi_session_id=str(row["magi_session_id"]),
        magi_user_id=str(row["magi_user_id"]),
        is_group=bool(row["is_group"]),
        created_at_ms=int(row["created_at_ms"]),
        last_active_at_ms=int(row["last_active_at_ms"]),
        metadata_json=str(row["metadata_json"]),
    )


class MysqlChannelSessionRepository:
    def __init__(self, database: MysqlDatabase) -> None:
        self._database = database

    async def initialize(self) -> None:
        async with self._database.transaction() as db:
            await db.execute(text("SELECT id FROM channel_session_mappings LIMIT 0"))

    async def lookup(
        self, channel_type: str, external_chat_id: str, *, external_thread_id: str | None = None
    ) -> ChannelSessionMapping | None:
        async with self._database.transaction() as db:
            row = (
                (
                    await db.execute(
                        text("SELECT * FROM channel_session_mappings WHERE identity_key=:key"),
                        {
                            "key": identity_key(
                                channel_type, external_chat_id, external_thread_id or ""
                            )
                        },
                    )
                )
                .mappings()
                .first()
            )
        return _mapping(row) if row is not None else None

    async def list_all(self) -> list[ChannelSessionMapping]:
        async with self._database.transaction() as db:
            rows = (
                (
                    await db.execute(
                        text(
                            "SELECT * FROM channel_session_mappings ORDER BY last_active_at_ms DESC,id DESC"
                        )
                    )
                )
                .mappings()
                .all()
            )
        return [_mapping(row) for row in rows]

    async def lookup_by_session(self, magi_session_id: str) -> ChannelSessionMapping | None:
        async with self._database.transaction() as db:
            row = (
                (
                    await db.execute(
                        text(
                            "SELECT * FROM channel_session_mappings WHERE session_key=:key ORDER BY id LIMIT 1"
                        ),
                        {"key": identity_key(magi_session_id)},
                    )
                )
                .mappings()
                .first()
            )
        return _mapping(row) if row is not None else None

    async def delete_mapping(
        self, channel_type: str, external_chat_id: str, *, external_thread_id: str | None = None
    ) -> None:
        async with self._database.transaction() as db:
            await db.execute(
                text("DELETE FROM channel_session_mappings WHERE identity_key=:key"),
                {"key": identity_key(channel_type, external_chat_id, external_thread_id or "")},
            )

    async def clear_conversation_state(self) -> dict[str, int]:
        counts = {}
        async with self._database.transaction() as db:
            for table in (
                "delivery_receipts",
                "outreach_outbox",
                "outreach_delivery_log",
                "channel_notification_cursors",
                "channel_session_mappings",
            ):
                counts[table] = int((await db.execute(text(f"DELETE FROM {table}"))).rowcount)
        return counts

    async def get_notification_cursor(self, channel_type: str, external_chat_id: str) -> int:
        async with self._database.transaction() as db:
            value = (
                await db.execute(
                    text(
                        "SELECT last_notification_id FROM channel_notification_cursors WHERE identity_key=:key"
                    ),
                    {"key": identity_key(channel_type, external_chat_id)},
                )
            ).scalar_one_or_none()
        return int(value or 0)

    async def update_notification_cursor(
        self, channel_type: str, external_chat_id: str, notification_id: int
    ) -> None:
        async with self._database.transaction() as db:
            await db.execute(
                text("""INSERT INTO channel_notification_cursors
                (identity_key, channel_type, external_chat_id, last_notification_id, updated_at_ms)
                VALUES (:key,:channel,:chat,:cursor,:now)
                ON DUPLICATE KEY UPDATE last_notification_id=:cursor,updated_at_ms=:now"""),
                {
                    "key": identity_key(channel_type, external_chat_id),
                    "channel": channel_type,
                    "chat": external_chat_id,
                    "cursor": notification_id,
                    "now": int(time.time() * 1000),
                },
            )

    async def get_relay_cursor(self, state_key: str) -> int:
        async with self._database.transaction() as db:
            value = (
                await db.execute(
                    text("SELECT value_integer FROM channel_relay_state WHERE identity_key=:key"),
                    {"key": identity_key(state_key)},
                )
            ).scalar_one_or_none()
        return int(value or 0)

    async def update_relay_cursor(self, state_key: str, notification_id: int) -> None:
        async with self._database.transaction() as db:
            await db.execute(
                text("""INSERT INTO channel_relay_state(identity_key,state_key,value_integer,updated_at_ms)
                VALUES (:key,:state,:cursor,:now) ON DUPLICATE KEY UPDATE value_integer=:cursor,updated_at_ms=:now"""),
                {
                    "key": identity_key(state_key),
                    "state": state_key,
                    "cursor": notification_id,
                    "now": int(time.time() * 1000),
                },
            )

    async def insert(self, mapping: ChannelSessionMapping) -> None:
        values = asdict(mapping)
        values["external_thread_id"] = mapping.external_thread_id or ""
        values["key"] = identity_key(
            mapping.channel_type, mapping.external_chat_id, mapping.external_thread_id or ""
        )
        values["session_key"] = identity_key(mapping.magi_session_id)
        async with self._database.transaction() as db:
            await db.execute(
                text("""INSERT INTO channel_session_mappings
                (identity_key,session_key,channel_type,external_chat_id,external_thread_id,magi_session_id,magi_user_id,
                 is_group,created_at_ms,last_active_at_ms,metadata_json)
                VALUES (:key,:session_key,:channel_type,:external_chat_id,:external_thread_id,:magi_session_id,:magi_user_id,
                    :is_group,:created_at_ms,:last_active_at_ms,:metadata_json)"""),
                values,
            )

    async def touch(
        self,
        channel_type: str,
        external_chat_id: str,
        now_ms: int,
        *,
        external_thread_id: str | None = None,
    ) -> None:
        async with self._database.transaction() as db:
            await db.execute(
                text(
                    "UPDATE channel_session_mappings SET last_active_at_ms=:now WHERE identity_key=:key"
                ),
                {
                    "key": identity_key(channel_type, external_chat_id, external_thread_id or ""),
                    "now": now_ms,
                },
            )


class MysqlDeliveryReceiptsRepository:
    def __init__(self, database: MysqlDatabase) -> None:
        self._database = database

    async def initialize(self) -> None:
        async with self._database.transaction() as db:
            await db.execute(text("SELECT receipt_id FROM delivery_receipts LIMIT 0"))

    async def save_receipts(
        self, *, session_id: str, run_id: str, revision: int, receipts: list[DeliveryReceipt]
    ) -> None:
        if not receipts:
            return
        values = [
            {
                "session_id": session_id,
                "run_id": run_id,
                "session_key": identity_key(session_id),
                "run_key": identity_key(run_id),
                "revision": revision,
                "channel": r.channel_id,
                "external": r.external_message_id,
                "magi_session": r.magi_session_id,
                "delivered": int(r.delivered_at_ms),
                "now": int(time.time() * 1000),
            }
            for r in receipts
        ]
        async with self._database.transaction() as db:
            await db.execute(
                text("""INSERT INTO delivery_receipts
                (session_key,run_key,session_id,run_id,revision,channel_id,external_message_id,magi_session_id,delivered_at_ms,created_at_ms)
                VALUES (:session_key,:run_key,:session_id,:run_id,:revision,:channel,:external,:magi_session,:delivered,:now)"""),
                values,
            )

    async def list_receipts(
        self, *, session_id: str, run_id: str, revision: int | None = None
    ) -> list[DeliveryReceipt]:
        sql = "SELECT * FROM delivery_receipts WHERE session_key=:session AND run_key=:run"
        parameters: dict[str, Any] = {
            "session": identity_key(session_id),
            "run": identity_key(run_id),
        }
        if revision is not None:
            sql += " AND revision=:revision"
            parameters["revision"] = revision
        async with self._database.transaction() as db:
            rows = (
                (await db.execute(text(sql + " ORDER BY receipt_id"), parameters)).mappings().all()
            )
        return [
            DeliveryReceipt(
                channel_id=r["channel_id"],
                external_message_id=r["external_message_id"],
                delivered_at_ms=int(r["delivered_at_ms"]),
                magi_session_id=r["magi_session_id"],
            )
            for r in rows
        ]

    async def clear_receipts(self, *, session_id: str, run_id: str) -> None:
        async with self._database.transaction() as db:
            await db.execute(
                text("DELETE FROM delivery_receipts WHERE session_key=:session AND run_key=:run"),
                {"session": identity_key(session_id), "run": identity_key(run_id)},
            )


class MysqlChannelBindingSettingsRepository:
    def __init__(self, database: MysqlDatabase) -> None:
        self._database = database

    async def initialize(self) -> None:
        async with self._database.transaction() as db:
            await db.execute(text("SELECT identity_key FROM channel_binding_settings LIMIT 0"))

    async def get(self, *, channel_type: str, external_user_id: str) -> ChannelBindingSettings:
        async with self._database.transaction() as db:
            row = (
                (
                    await db.execute(
                        text("SELECT * FROM channel_binding_settings WHERE identity_key=:key"),
                        {"key": identity_key(channel_type, external_user_id)},
                    )
                )
                .mappings()
                .first()
            )
        return ChannelBindingSettings(
            channel_type=channel_type,
            external_user_id=external_user_id,
            auto_approve=bool(row["auto_approve"]) if row is not None else False,
            updated_at_ms=int(row["updated_at_ms"]) if row is not None else 0,
        )

    async def set_auto_approve(
        self, *, channel_type: str, external_user_id: str, auto_approve: bool
    ) -> ChannelBindingSettings:
        if not channel_type.strip() or not external_user_id.strip():
            raise ValueError("Channel and external user identity must be non-empty")
        now = int(time.time() * 1000)
        async with self._database.transaction() as db:
            await db.execute(
                text("""INSERT INTO channel_binding_settings
                (identity_key,channel_type,external_user_id,auto_approve,updated_at_ms)
                VALUES (:key,:channel,:user,:approve,:now)
                ON DUPLICATE KEY UPDATE auto_approve=:approve,updated_at_ms=:now"""),
                {
                    "key": identity_key(channel_type, external_user_id),
                    "channel": channel_type,
                    "user": external_user_id,
                    "approve": auto_approve,
                    "now": now,
                },
            )
        return ChannelBindingSettings(channel_type, external_user_id, auto_approve, now)

    async def list_all(self) -> list[ChannelBindingSettings]:
        async with self._database.transaction() as db:
            rows = (
                (
                    await db.execute(
                        text(
                            "SELECT * FROM channel_binding_settings ORDER BY updated_at_ms DESC,identity_key"
                        )
                    )
                )
                .mappings()
                .all()
            )
        return [
            ChannelBindingSettings(
                str(r["channel_type"]),
                str(r["external_user_id"]),
                bool(r["auto_approve"]),
                int(r["updated_at_ms"]),
            )
            for r in rows
        ]
