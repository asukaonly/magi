"""Plugin ingress event queue persistence."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import hashlib
import json
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
                        "DELETE FROM plugin_ingress_events WHERE occurred_at_ms <= ? AND source_kind != 'background_delivery'",
                        (cutoff_ms,),
                    )
                cursor = await db.execute(
                    """
                    UPDATE plugin_ingress_events
                    SET status = 'claimed',
                        claimed_by = ?,
                        claimed_at_ms = ?
                    WHERE event_id = (
                        SELECT e.event_id
                        FROM plugin_ingress_events e
                        WHERE e.status = 'pending' AND e.next_attempt_at_ms <= ?
                          AND NOT EXISTS (
                            SELECT 1 FROM plugin_ingress_events older
                            WHERE e.source_kind = 'background_delivery'
                              AND older.source_kind = e.source_kind
                              AND older.producer = e.producer AND older.cursor_key = e.cursor_key
                              AND older.event_id < e.event_id
                              AND older.status IN ('pending', 'claimed', 'failed')
                          )
                        ORDER BY e.created_at_ms ASC, e.event_id ASC
                        LIMIT 1
                    )
                    RETURNING *
                    """,
                    (consumer_name, now_ms, now_ms),
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
            await db.execute("DELETE FROM background_delivery_receipts")
            await db.commit()
            return max(0, int(cursor.rowcount or 0))

    async def accept_background_event(
        self, *, producer_id: str, data_epoch: str, event_id: str,
        stream: str, sequence: int, record: PluginIngressEventRecord, allow_new: bool = True,
    ) -> str:
        """Commit the deduplication receipt and the work item in one transaction."""
        fingerprint = hashlib.sha256(json.dumps({
            "stream": stream, "sequence": sequence, "occurred": record.occurred_at_ms,
            "target": record.plugin_target, "type": record.event_type,
            "payload": json.loads(record.payload_json),
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        async with self.plugin_ingress_operation():
            await self.initialize()
            async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
                await db.execute("PRAGMA synchronous=FULL")
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    "SELECT fingerprint FROM background_delivery_receipts WHERE producer_id=? AND data_epoch=? AND event_id=?",
                    (producer_id, data_epoch, event_id),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    return "accepted" if existing[0] == fingerprint else "event_identity_conflict"
                if not allow_new:
                    return "handler_not_replay_safe"
                cursor = await db.execute(
                    "SELECT MAX(sequence) FROM background_delivery_receipts WHERE producer_id=? AND data_epoch=? AND stream=?",
                    (producer_id, data_epoch, stream),
                )
                previous = (await cursor.fetchone())[0]
                if previous is not None and sequence <= previous:
                    return "stream_sequence_conflict"
                # The gateway validates data_epoch under its maintenance permit.
                # Device clocks are not an authority for clearing remote observations.
                cursor = await db.execute(
                    "SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(payload_json AS BLOB))),0) FROM plugin_ingress_events WHERE status != 'completed'",
                )
                count, size = await cursor.fetchone()
                if count >= 10000 or size + len(record.payload_json.encode()) > 64 * 1024 * 1024:
                    return "inbox_full"
                await db.execute(
                    "INSERT INTO background_delivery_receipts VALUES (?,?,?,?,?,?,?)",
                    (producer_id, data_epoch, event_id, stream, sequence, fingerprint, self._now_ms()),
                )
                await db.execute("""
                    INSERT INTO plugin_ingress_events
                    (source_kind, producer, plugin_target, event_type, occurred_at_ms,
                     payload_json, cursor_key, status, created_at_ms, delivery_epoch)
                    VALUES ('background_delivery',?,?,?,?,?,?,'pending',?,?)
                """, (producer_id, record.plugin_target, record.event_type, record.occurred_at_ms,
                      record.payload_json, stream, self._now_ms(), data_epoch))
                await db.commit()
                return "accepted"

    async def recover_background_delivery_claims(self, *, data_epoch: str) -> None:
        """Retire replaced data, then recover replay-safe work after the old worker exits."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("PRAGMA secure_delete=ON")
            await db.execute("PRAGMA synchronous=FULL")
            await db.execute("DELETE FROM plugin_ingress_events WHERE source_kind='background_delivery' AND delivery_epoch IS NOT ?", (data_epoch,))
            await db.execute("DELETE FROM background_delivery_receipts WHERE data_epoch != ?", (data_epoch,))
            await db.execute("""UPDATE plugin_ingress_events
                SET status='pending', claimed_by=NULL, claimed_at_ms=NULL
                WHERE source_kind='background_delivery' AND status='claimed'""")
            await db.commit()

    async def retry_background_delivery(self, event_id: int) -> None:
        """Back off transient handler failures; retain exhausted work for inspection."""
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("""UPDATE plugin_ingress_events
                SET status=CASE WHEN attempts >= 9 THEN 'failed' ELSE 'pending' END,
                    next_attempt_at_ms=? + MIN(300000, 1000 * (1 << MIN(attempts, 8))),
                    attempts=attempts+1, claimed_by=NULL, claimed_at_ms=NULL,
                    last_error='handler_failed'
                WHERE event_id=?""", (self._now_ms(), event_id))
            await db.commit()

    async def background_delivery_status(self) -> dict[str, int]:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute("""SELECT
                COALESCE(SUM(status IN ('pending','claimed')),0),
                COALESCE(SUM(status='failed'),0)
                FROM plugin_ingress_events WHERE source_kind='background_delivery'""")
            pending, failed = await cursor.fetchone()
            return {"pending": pending, "failed": failed}

    async def retry_failed_background_deliveries(self) -> None:
        async with self.plugin_ingress_operation():
            async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
                await db.execute("""UPDATE plugin_ingress_events
                    SET status='pending', attempts=0, next_attempt_at_ms=0, last_error=NULL
                    WHERE source_kind='background_delivery' AND status='failed'""")
                await db.commit()

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
