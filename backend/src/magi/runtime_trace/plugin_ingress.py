"""Plugin ingress event queue persistence."""

from __future__ import annotations

from typing import Any, TypeVar

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .contracts import PluginIngressEventRecord

T = TypeVar("T")


class PluginIngressPersistenceMixin:
    """Persist and claim plugin ingress events."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        raise NotImplementedError

    def _row_to_record(self, record_type: type[T], row: aiosqlite.Row | None) -> T | None:
        raise NotImplementedError

    @staticmethod
    def _now_ms() -> int:
        raise NotImplementedError

    async def append_plugin_ingress_event(self, record: PluginIngressEventRecord) -> int:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                """
                INSERT INTO plugin_ingress_events (
                    source_kind,
                    producer,
                    plugin_target,
                    event_type,
                    occurred_at_ms,
                    payload_json,
                    cursor_key,
                    status,
                    claimed_by,
                    claimed_at_ms,
                    processed_at_ms,
                    last_error,
                    created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source_kind,
                    record.producer,
                    record.plugin_target,
                    record.event_type,
                    int(record.occurred_at_ms),
                    record.payload_json,
                    record.cursor_key,
                    record.status or "pending",
                    record.claimed_by,
                    record.claimed_at_ms,
                    record.processed_at_ms,
                    record.last_error,
                    int(record.created_at_ms or self._now_ms()),
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def claim_next_plugin_ingress_event(self, *, consumer_name: str) -> PluginIngressEventRecord | None:
        await self.initialize()
        now_ms = self._now_ms()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                UPDATE plugin_ingress_events
                SET status = 'claimed',
                    claimed_by = ?,
                    claimed_at_ms = ?
                WHERE event_id = (
                    SELECT event_id
                    FROM plugin_ingress_events
                    WHERE status = 'pending'
                    ORDER BY created_at_ms ASC, event_id ASC
                    LIMIT 1
                )
                RETURNING *
                """,
                (consumer_name, now_ms),
            )
            row = await cursor.fetchone()
            await db.commit()
        return self._row_to_record(PluginIngressEventRecord, row)

    async def complete_plugin_ingress_event(self, event_id: int) -> None:
        await self._update_plugin_ingress_event_status(
            event_id=event_id,
            status="completed",
            error_text=None,
        )

    async def fail_plugin_ingress_event(self, event_id: int, *, error_text: str | None = None) -> None:
        await self._update_plugin_ingress_event_status(
            event_id=event_id,
            status="failed",
            error_text=error_text,
        )

    async def get_plugin_ingress_event(self, event_id: int) -> PluginIngressEventRecord | None:
        await self.initialize()
        row = await self._fetchone(
            "SELECT * FROM plugin_ingress_events WHERE event_id = ?",
            (int(event_id),),
        )
        return self._row_to_record(PluginIngressEventRecord, row)

    async def _update_plugin_ingress_event_status(
        self,
        *,
        event_id: int,
        status: str,
        error_text: str | None,
    ) -> None:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                """
                UPDATE plugin_ingress_events
                SET status = ?,
                    processed_at_ms = ?,
                    last_error = ?
                WHERE event_id = ?
                """,
                (
                    status,
                    self._now_ms(),
                    error_text,
                    int(event_id),
                ),
            )
            await db.commit()