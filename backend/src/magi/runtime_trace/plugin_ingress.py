"""Plugin ingress event queue persistence."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import aiosqlite

from ..core.sqlite import secure_compact_sqlite, sqlite_connection_async
from .contracts import PluginIngressClearStateReader, PluginIngressEventRecord

T = TypeVar("T")


class PluginIngressPersistenceMixin:
    """Persist and claim plugin ingress events."""

    db_path: str
    _plugin_ingress_clear_state_reader: PluginIngressClearStateReader | None
    _plugin_ingress_barrier: Any

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        raise NotImplementedError

    def _row_to_record(self, record_type: type[T], row: aiosqlite.Row | None) -> T | None:
        raise NotImplementedError

    @staticmethod
    def _now_ms() -> int:
        raise NotImplementedError

    @asynccontextmanager
    async def plugin_ingress_operation(self) -> AsyncIterator[None]:
        """Keep one queue operation or handler inside the shared boundary."""
        async with self._plugin_ingress_barrier.operation():
            yield

    @asynccontextmanager
    async def plugin_ingress_global_clear_boundary(self) -> AsyncIterator[None]:
        """Keep the ingress queue empty throughout a full user-data clear."""
        async with self._plugin_ingress_barrier.exclusive():
            try:
                await self._clear_plugin_ingress_events_unlocked()
                yield
            finally:
                await self._clear_plugin_ingress_events_unlocked()
                await secure_compact_sqlite(self.db_path, profile="hot_write")

    async def append_plugin_ingress_event(self, record: PluginIngressEventRecord) -> int:
        async with self.plugin_ingress_operation():
            await self.initialize()
            cutoff_ms = await self._plugin_ingress_clear_cutoff_ms()
            if cutoff_ms is not None and int(record.occurred_at_ms or 0) <= cutoff_ms:
                return 0
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

    async def claim_next_plugin_ingress_event(
        self,
        *,
        consumer_name: str,
    ) -> PluginIngressEventRecord | None:
        async with self.plugin_ingress_operation():
            await self.initialize()
            now_ms = self._now_ms()
            cutoff_ms = await self._plugin_ingress_clear_cutoff_ms()
            async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
                db.row_factory = aiosqlite.Row
                if cutoff_ms is not None:
                    await db.execute(
                        "DELETE FROM plugin_ingress_events WHERE occurred_at_ms <= ?",
                        (cutoff_ms,),
                    )
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

    async def clear_plugin_ingress_events(self) -> int:
        """Delete every queued or processed plugin ingress payload."""
        async with self.plugin_ingress_operation():
            return await self._clear_plugin_ingress_events_unlocked()

    async def _clear_plugin_ingress_events_unlocked(self) -> int:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute("DELETE FROM plugin_ingress_events")
            await db.commit()
            return max(0, int(cursor.rowcount or 0))

    async def _plugin_ingress_clear_cutoff_ms(self) -> int | None:
        reader = self._plugin_ingress_clear_state_reader
        if reader is None:
            return None
        generation, cutoff_seconds = await reader()
        if generation <= 0:
            return None
        return int(cutoff_seconds * 1000)

    async def complete_plugin_ingress_event(self, event_id: int) -> None:
        await self._update_plugin_ingress_event_status(
            event_id=event_id,
            status="completed",
            error_text=None,
        )

    async def fail_plugin_ingress_event(
        self,
        event_id: int,
        *,
        error_text: str | None = None,
    ) -> None:
        await self._update_plugin_ingress_event_status(
            event_id=event_id,
            status="failed",
            error_text=error_text,
        )

    async def get_plugin_ingress_event(
        self,
        event_id: int,
    ) -> PluginIngressEventRecord | None:
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
