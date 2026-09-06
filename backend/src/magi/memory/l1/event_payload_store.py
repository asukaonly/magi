"""Pinned capture-time full-text payloads for L1 events (RFC #56 P3).

``l1_event_payload`` is a sparse satellite of ``fact_events``: a row exists only
when a source pinned the capture-time full text for an event (obsidian note body,
git commit text). ``fact_events.content`` stays a lean summary — cheap for the
timeline and L1 reads — while L2 reads the frozen full body from here at
extraction time and falls back to ``content`` when no row exists.

Hard rule (RFC #56 P3): L2 reads the pinned snapshot or ``content``; it never
re-fetches from the live source. The snapshot is frozen at capture.

Schema is alembic-owned (the L1 v1 baseline plus the composed ``SCHEMA_SQL``
applied by ``L1EventLifecycleMixin._ensure_schema``); this store only
reads/writes rows and never issues DDL.
"""
from __future__ import annotations

import time

import aiosqlite

L1_EVENT_PAYLOAD_TABLE = "l1_event_payload"


class L1EventPayloadStore:
    """SQLite-backed reader/writer for pinned L1 full-text payloads."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def put(self, event_id: str, content: str, *, now: float | None = None) -> None:
        """Pin ``content`` for ``event_id`` (replaces any existing payload).

        Standalone-connection write; the L1 write path pins co-transactionally
        with the event insert instead (see ``L1EventWriteMixin.store``). This is
        the convenience/out-of-band entry point used by callers and tests.
        """
        stamp = time.time() if now is None else now
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"INSERT OR REPLACE INTO {L1_EVENT_PAYLOAD_TABLE} "
                "(event_id, content, created_at) VALUES (?, ?, ?)",
                (event_id, content, stamp),
            )
            await db.commit()

    async def get(self, event_id: str) -> str | None:
        """Return the pinned full text for ``event_id``, or ``None`` if absent."""
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                f"SELECT content FROM {L1_EVENT_PAYLOAD_TABLE} WHERE event_id = ?",
                (event_id,),
            )
            row = await cur.fetchone()
            return str(row[0]) if row is not None else None

    async def get_many(self, event_ids: list[str]) -> dict[str, str]:
        """Batch ``get`` for a window of events; absent ids are simply omitted."""
        ids = [e for e in event_ids if e]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                f"SELECT event_id, content FROM {L1_EVENT_PAYLOAD_TABLE} "
                f"WHERE event_id IN ({placeholders})",
                ids,
            )
            rows = await cur.fetchall()
            return {str(r[0]): str(r[1]) for r in rows}

    async def prune_stale(self, *, retention_seconds: float, now: float | None = None) -> int:
        """Delete payloads older than the retention window; return rows deleted.

        Pinned payloads are a transient extraction aid — once L2 has consumed an
        event (which happens shortly after ingest) the full body is no longer
        needed, so a time-based prune keeps the table bounded without touching
        the parent event. Returns the number of rows deleted.
        """
        stamp = time.time() if now is None else now
        cutoff = stamp - float(retention_seconds)
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                f"DELETE FROM {L1_EVENT_PAYLOAD_TABLE} WHERE created_at < ?",
                (cutoff,),
            )
            await db.commit()
            return int(cur.rowcount)
