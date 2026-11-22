"""Per-(source_type, key) promotion counter for frequency-gated L2 admission (RFC #56 P2).

A source with a frequency policy declares a ``promotion_key`` per event (e.g. the
domain for browser history). This store accumulates a count per key, reports whether a
key has crossed its threshold ("promoted"), and prunes stale non-promoted keys so the
table stays bounded.

Below threshold the caller runs the event structured-only (deterministic direct-writes,
skip the LLM — reusing P1); once promoted, full L2 runs and stays on for that key.

A rolling-window flood cap bounds how many keys may *newly* promote per window so a
backfill/re-sync burst cannot trigger a spike of full-L2 (LLM) extractions; over-cap
crossings stay structured-only and re-promote on a later event once the burst subsides.

Counting is idempotent per event id (a re-synced / replayed event is not double-counted).
"""
from __future__ import annotations

import time

import aiosqlite


# Flood cap (RFC #56 P2): the extract worker is a streaming queue consumer with no
# discrete "drain batch", so a backfill/re-sync that makes many keys cross threshold at
# once would promote them all back-to-back -> a burst of full-L2 (LLM) extractions ->
# cost spike. We cap how many keys may *newly* promote within a rolling time window;
# over-cap crossings stay structured-only this round and re-promote on a later event once
# the burst subsides. Normal operation promotes keys sparsely and never approaches the cap.
_DEFAULT_PROMOTE_CAP = 10
_DEFAULT_PROMOTE_WINDOW_SECONDS = 60.0
_DEFAULT_LLM_COOLDOWN_SECONDS = 6 * 3600.0
_DEFAULT_PROMOTED_RETENTION_SECONDS = 90 * 86400.0


class L2PromotionCounter:
    """SQLite-backed frequency accumulator for L2 promotion decisions."""

    def __init__(
        self,
        db_path: str,
        *,
        promote_cap: int | None = _DEFAULT_PROMOTE_CAP,
        promote_window_seconds: float = _DEFAULT_PROMOTE_WINDOW_SECONDS,
        llm_cooldown_seconds: float | None = _DEFAULT_LLM_COOLDOWN_SECONDS,
        promoted_retention_seconds: float = _DEFAULT_PROMOTED_RETENTION_SECONDS,
    ) -> None:
        self._db_path = db_path
        # ``promote_cap=None`` disables the cap (uncapped, legacy behaviour).
        self._promote_cap = promote_cap
        self._promote_window_seconds = float(promote_window_seconds)
        self._llm_cooldown_seconds = (
            float(llm_cooldown_seconds)
            if llm_cooldown_seconds is not None and float(llm_cooldown_seconds) > 0
            else None
        )
        self._promoted_retention_seconds = max(0.0, float(promoted_retention_seconds))

    @staticmethod
    async def _ensure(db: aiosqlite.Connection) -> None:
        """Create tables if absent (idempotent). Called by every op so the store is
        usable without a separate initialize() step in the host's construction flow."""
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS l2_promotion_counter (
                source_type           TEXT NOT NULL,
                key                   TEXT NOT NULL,
                count                 INTEGER NOT NULL DEFAULT 0,
                promoted              INTEGER NOT NULL DEFAULT 0,
                first_seen            REAL NOT NULL,
                last_seen             REAL NOT NULL,
                promoted_at           REAL,
                last_llm_extracted_at REAL,
                PRIMARY KEY (source_type, key)
            )
            """
        )
        cols = {
            r[1] for r in await (await db.execute("PRAGMA table_info(l2_promotion_counter)")).fetchall()
        }
        if "promoted_at" not in cols:
            try:
                await db.execute("ALTER TABLE l2_promotion_counter ADD COLUMN promoted_at REAL")
            except aiosqlite.OperationalError:
                pass
        if "last_llm_extracted_at" not in cols:
            try:
                await db.execute(
                    "ALTER TABLE l2_promotion_counter ADD COLUMN last_llm_extracted_at REAL"
                )
            except aiosqlite.OperationalError:
                pass
        # The flood-cap counts recent promotions by promoted_at on every newly-eligible bump.
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_l2_promotion_promoted_at "
            "ON l2_promotion_counter(promoted_at)"
        )
        # Idempotency ledger: one row per counted event. seen_at lets prune bound it.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS l2_promotion_seen (
                event_id TEXT PRIMARY KEY,
                seen_at  REAL NOT NULL,
                admitted INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        seen_cols = {
            r[1] for r in await (await db.execute("PRAGMA table_info(l2_promotion_seen)")).fetchall()
        }
        if "admitted" not in seen_cols:
            try:
                await db.execute(
                    "ALTER TABLE l2_promotion_seen ADD COLUMN admitted INTEGER NOT NULL DEFAULT 0"
                )
            except aiosqlite.OperationalError:
                pass

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await self._ensure(db)
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
        """Count one event for (source_type, key); return ``(count, llm_admitted)``.

        Idempotent: an ``event_id`` already counted returns the stored count and admission
        decision without double-counting. Once ``count >= threshold`` and the flood cap
        admits promotion, the key runs full L2 extraction and enters a per-key cooldown
        window during which repeated events downgrade to structured-only while still
        advancing ``count`` and ``last_seen``.
        """
        stamp = time.time() if now is None else now
        async with aiosqlite.connect(self._db_path) as db:
            await self._ensure(db)
            await db.commit()
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                "SELECT count, promoted, promoted_at, last_llm_extracted_at "
                "FROM l2_promotion_counter WHERE source_type = ? AND key = ?",
                (source_type, key),
            )
            row = await cur.fetchone()
            count = int(row[0]) if row else 0
            promoted = bool(row[1]) if row else False
            promoted_at = row[2] if row else None
            last_llm_extracted_at = row[3] if row else None

            seen = await db.execute(
                "SELECT admitted FROM l2_promotion_seen WHERE event_id = ?", (event_id,)
            )
            seen_row = await seen.fetchone()
            if seen_row is not None:
                return count, bool(seen_row[0])

            count += 1
            llm_admitted = False
            if not promoted:
                if count >= max(1, int(threshold)):
                    # Newly crossing threshold: gate the promotion through the flood cap so a
                    # backfill burst cannot promote a large batch of keys in one window.
                    if await self._promotion_within_cap(db, stamp):
                        promoted = True
                        promoted_at = stamp
                        last_llm_extracted_at = stamp
                        llm_admitted = True
            else:
                cooldown = self._llm_cooldown_seconds
                if (
                    cooldown is None
                    or last_llm_extracted_at is None
                    or (stamp - float(last_llm_extracted_at)) >= cooldown
                ):
                    last_llm_extracted_at = stamp
                    llm_admitted = True

            await db.execute(
                "INSERT INTO l2_promotion_seen (event_id, seen_at, admitted) VALUES (?, ?, ?)",
                (event_id, stamp, 1 if llm_admitted else 0),
            )

            if row is not None:
                await db.execute(
                    "UPDATE l2_promotion_counter SET count = ?, promoted = ?, last_seen = ?, "
                    "promoted_at = ?, last_llm_extracted_at = ? "
                    "WHERE source_type = ? AND key = ?",
                    (
                        count,
                        1 if promoted else 0,
                        stamp,
                        promoted_at,
                        last_llm_extracted_at,
                        source_type,
                        key,
                    ),
                )
            else:
                await db.execute(
                    "INSERT INTO l2_promotion_counter "
                    "(source_type, key, count, promoted, first_seen, last_seen, "
                    "promoted_at, last_llm_extracted_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        source_type,
                        key,
                        count,
                        1 if promoted else 0,
                        stamp,
                        stamp,
                        promoted_at,
                        last_llm_extracted_at,
                    ),
                )
            await db.commit()
            return count, llm_admitted

    async def _promotion_within_cap(self, db: aiosqlite.Connection, stamp: float) -> bool:
        """Whether a new promotion at ``stamp`` fits under the rolling-window cap.

        Counts keys promoted within ``(stamp - window, stamp]`` and admits while that count
        is below the cap. The current key is still ``promoted = 0`` at call time, so it is
        never self-counted. ``promote_cap=None`` disables the cap (always admits).
        """
        if self._promote_cap is None:
            return True
        window_start = stamp - self._promote_window_seconds
        cur = await db.execute(
            "SELECT COUNT(*) FROM l2_promotion_counter "
            "WHERE promoted = 1 AND promoted_at IS NOT NULL AND promoted_at >= ?",
            (window_start,),
        )
        recent = int((await cur.fetchone())[0])
        return recent < self._promote_cap

    async def prune_stale(
        self,
        *,
        retention_seconds: float,
        promoted_retention_seconds: float | None = None,
        now: float | None = None,
    ) -> int:
        """Delete stale unpromoted keys and long-inactive promoted keys.

        Unpromoted keys expire after ``retention_seconds``; promoted keys naturally
        decay after ``promoted_retention_seconds`` (default 90 days) of inactivity so
        abandoned high-frequency keys do not remain permanently promoted forever.
        Returns the total number of counter rows deleted.
        """
        stamp = time.time() if now is None else now
        unpromoted_cutoff = stamp - float(retention_seconds)
        effective_promoted_ttl = (
            float(promoted_retention_seconds)
            if promoted_retention_seconds is not None
            else self._promoted_retention_seconds
        )
        promoted_cutoff = stamp - max(0.0, effective_promoted_ttl)
        async with aiosqlite.connect(self._db_path) as db:
            await self._ensure(db)
            cur = await db.execute(
                "DELETE FROM l2_promotion_counter "
                "WHERE (promoted = 0 AND last_seen < ?) OR (promoted = 1 AND last_seen < ?)",
                (unpromoted_cutoff, promoted_cutoff),
            )
            deleted = cur.rowcount
            await db.execute(
                "DELETE FROM l2_promotion_seen WHERE seen_at < ?",
                (unpromoted_cutoff,),
            )
            await db.commit()
            return int(deleted)
