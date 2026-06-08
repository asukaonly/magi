"""Per-(source_type, key) promotion counter for frequency-gated L2 admission (RFC #56 P2).

A sensor with a frequency policy declares a ``promotion_key`` per event (e.g. the
domain for browser history). This store accumulates a count per key, reports whether a
key has crossed its threshold ("promoted"), and prunes stale non-promoted keys so the
table stays bounded.

Below threshold the caller runs the event structured-only (deterministic direct-writes,
skip the LLM — reusing P1); once promoted, full L2 runs and stays on for that key.

Counting is idempotent per event id (a re-synced / replayed event is not double-counted).
"""
from __future__ import annotations

import time

import aiosqlite


class L2PromotionCounter:
    """SQLite-backed frequency accumulator for L2 promotion decisions."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS l2_promotion_counter (
                    source_type TEXT NOT NULL,
                    key         TEXT NOT NULL,
                    count       INTEGER NOT NULL DEFAULT 0,
                    promoted    INTEGER NOT NULL DEFAULT 0,
                    first_seen  REAL NOT NULL,
                    last_seen   REAL NOT NULL,
                    PRIMARY KEY (source_type, key)
                )
                """
            )
            # Idempotency ledger: one row per counted event. seen_at lets prune bound it.
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS l2_promotion_seen (
                    event_id TEXT PRIMARY KEY,
                    seen_at  REAL NOT NULL
                )
                """
            )
            await db.commit()

    async def bump(
        self,
        source_type: str,
        key: str,
        event_id: str,
        *,
        threshold: int,
        now: float | None = None,
    ) -> tuple[int, bool]:
        """Count one event for (source_type, key); return ``(count, promoted)``.

        Idempotent: an ``event_id`` already counted returns the current state unchanged.
        ``promoted`` flips True once ``count >= threshold`` and never flips back.
        """
        stamp = time.time() if now is None else now
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "SELECT count, promoted FROM l2_promotion_counter WHERE source_type = ? AND key = ?",
                (source_type, key),
            )
            row = await cur.fetchone()
            count = int(row[0]) if row else 0
            promoted = bool(row[1]) if row else False

            seen = await db.execute(
                "SELECT 1 FROM l2_promotion_seen WHERE event_id = ?", (event_id,)
            )
            if await seen.fetchone() is not None:
                return count, promoted  # already counted this event — no double count

            await db.execute(
                "INSERT INTO l2_promotion_seen (event_id, seen_at) VALUES (?, ?)",
                (event_id, stamp),
            )
            count += 1
            if count >= max(1, int(threshold)):
                promoted = True

            if row is not None:
                await db.execute(
                    "UPDATE l2_promotion_counter SET count = ?, promoted = ?, last_seen = ? "
                    "WHERE source_type = ? AND key = ?",
                    (count, 1 if promoted else 0, stamp, source_type, key),
                )
            else:
                await db.execute(
                    "INSERT INTO l2_promotion_counter "
                    "(source_type, key, count, promoted, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (source_type, key, count, 1 if promoted else 0, stamp, stamp),
                )
            await db.commit()
            return count, promoted

    async def prune_stale(self, *, retention_seconds: float, now: float | None = None) -> int:
        """Delete non-promoted keys whose ``last_seen`` predates the retention window.

        Promoted keys are kept (the "known-signal" set + a guard against re-accumulation).
        The idempotency ledger is trimmed of equally-old entries to stay bounded.
        Returns the number of counter rows deleted.
        """
        stamp = time.time() if now is None else now
        cutoff = stamp - float(retention_seconds)
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "DELETE FROM l2_promotion_counter WHERE promoted = 0 AND last_seen < ?",
                (cutoff,),
            )
            deleted = cur.rowcount
            await db.execute("DELETE FROM l2_promotion_seen WHERE seen_at < ?", (cutoff,))
            await db.commit()
            return int(deleted)
