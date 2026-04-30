"""Idempotency lookup helpers for L1 event retrieval."""

from __future__ import annotations

from typing import Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...event_contracts import MemoryEvent
from .common import FACT_EVENTS_TABLE, L1EventQueryHostProtocol


class L1EventIdempotencyMixin:
    """Resolve existing event IDs by event ID or business idempotency tuple."""

    async def find_event_id_by_idempotency(
        self,
        *,
        source: str,
        event_type: str,
        idempotency_key: str | None,
    ) -> Optional[str]:
        """Find an existing event id by business idempotency tuple."""
        host = cast(L1EventQueryHostProtocol, self)
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key:
            return None
        await host.initialize()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            return await self._find_event_id_by_idempotency(
                db,
                source=source,
                event_type=event_type,
                idempotency_key=normalized_key,
            )

    async def _resolve_existing_event_id(
        self,
        db: aiosqlite.Connection,
        event: MemoryEvent,
    ) -> str | None:
        if event.idempotency_key:
            existing = await self._find_event_id_by_idempotency(
                db,
                source=event.source,
                event_type=event.event_type,
                idempotency_key=event.idempotency_key,
            )
            if existing:
                return existing
        async with db.execute(
            f"SELECT event_id FROM {FACT_EVENTS_TABLE} WHERE event_id = ?",
            (event.event_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0])

    async def _find_event_id_by_idempotency(
        self,
        db: aiosqlite.Connection,
        *,
        source: str,
        event_type: str,
        idempotency_key: str,
    ) -> str | None:
        async with db.execute(
            f"""
            SELECT event_id
            FROM {FACT_EVENTS_TABLE}
            WHERE source = ? AND event_type = ? AND idempotency_key = ?
            LIMIT 1
            """,
            (source, event_type, idempotency_key),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0])


__all__ = ["L1EventIdempotencyMixin"]