"""Assertion lifecycle helpers for L2 entity maintenance."""

from __future__ import annotations

import time
from typing import Any, Protocol

import aiosqlite

from .....core.logger import get_logger
from .....core.sqlite import sqlite_connection_async

logger = get_logger("magi.memory.l2.entities.maintenance")


class _AssertionMaintenanceStatsProtocol(Protocol):
    expired_assertions: int
    stale_snapshots_cleaned: int
    entities_reconciled: int
    snapshots_refreshed: int
    errors: list[str]


class _AssertionMaintenanceHostProtocol(Protocol):
    _db_path: str
    _cognition_store: Any | None
    FAST_DECAY_TTL: float
    SESSION_DECAY_TTL: float
    RECONCILE_STALE_THRESHOLD: float
    RECONCILE_BATCH_SIZE: int
    RECONCILE_MAX_TOTAL: int


class L2EntityAssertionMaintenanceMixin:
    """Maintain assertion expiry, stale snapshots, and stale entity reconciliation."""

    async def _expire_decayed_assertions(
        self,
        stats: _AssertionMaintenanceStatsProtocol,
    ) -> None:
        """Expire assertions whose decay policy indicates they have outlived their TTL.

        - ``fast_decay`` (annoyance, irritation, frustration): expire after
          ``FAST_DECAY_TTL`` seconds since last update.
        - ``session_decay`` (mood, engagement): expire after
          ``SESSION_DECAY_TTL`` seconds since last update.
        - Assertions that already have an explicit ``expires_at`` in the past
          are also marked expired.
        """
        host = self._assertion_maintenance_host()
        now = time.time()
        fast_cutoff = now - host.FAST_DECAY_TTL
        session_cutoff = now - host.SESSION_DECAY_TTL
        async with sqlite_connection_async(host._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions
                SET validation_state = 'expired', status = 'expired', updated_at = ?
                WHERE validation_state NOT IN ('expired', 'user_rejected', 'contradicted')
                  AND status NOT IN ('superseded', 'archived')
                  AND (
                    (expires_at IS NOT NULL AND expires_at < ?)
                    OR (decay_policy = 'fast_decay' AND updated_at < ?)
                    OR (decay_policy = 'session_decay' AND updated_at < ?)
                  )
                """,
                (now, now, fast_cutoff, session_cutoff),
            )
            stats.expired_assertions = cursor.rowcount
            await db.commit()

    async def _clean_stale_snapshots(
        self,
        stats: _AssertionMaintenanceStatsProtocol,
    ) -> None:
        """Delete snapshots for entities that have no active/corroborated/tentative assertions."""
        host = self._assertion_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM tom_snapshots
                WHERE entity_id NOT IN (
                    SELECT DISTINCT entity_id FROM tom_trait_assertions
                    WHERE validation_state IN ('tentative', 'corroborated', 'stable')
                      AND status NOT IN ('superseded', 'archived', 'expired', 'user_rejected')
                )
                """
            )
            cleaned = cursor.rowcount
            if cleaned:
                await db.commit()
            stats.stale_snapshots_cleaned = cleaned

    async def _reconcile_stale_entities(
        self,
        stats: _AssertionMaintenanceStatsProtocol,
    ) -> None:
        """Re-reconcile entities whose assertions haven't been reviewed recently."""
        host = self._assertion_maintenance_host()
        store = host._cognition_store
        if store is None:
            from ...store import L2CognitionStore

            store = L2CognitionStore(db_path=host._db_path)
            await store.initialize()

        stale_cutoff = time.time() - host.RECONCILE_STALE_THRESHOLD
        total_processed = 0
        last_updated_at: float = 0.0

        while total_processed < host.RECONCILE_MAX_TOTAL:
            async with sqlite_connection_async(host._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT DISTINCT entity_id, entity_type, MIN(updated_at) AS min_updated
                    FROM tom_trait_assertions
                    WHERE validation_state IN ('tentative', 'corroborated')
                      AND status NOT IN ('superseded', 'archived', 'expired', 'user_rejected')
                      AND updated_at < ?
                      AND updated_at > ?
                    GROUP BY entity_id, entity_type
                    ORDER BY min_updated ASC
                    LIMIT ?
                    """,
                    (stale_cutoff, last_updated_at, host.RECONCILE_BATCH_SIZE),
                ) as cursor:
                    rows = await cursor.fetchall()

            if not rows:
                break

            for row in rows:
                entity_id = str(row["entity_id"])
                entity_type = str(row["entity_type"])
                last_updated_at = float(row["min_updated"])
                try:
                    outcomes = await store.reconcile_entity(
                        entity_id=entity_id,
                        entity_type=entity_type,
                    )
                    if outcomes:
                        stats.entities_reconciled += 1
                        await store.refresh_entity_snapshot(
                            entity_id=entity_id,
                            entity_type=entity_type,
                        )
                        stats.snapshots_refreshed += 1
                except Exception as exc:
                    stats.errors.append(f"reconcile {entity_id}: {exc}")
                    logger.warning(
                        "L2 maintenance reconcile failed for entity",
                        entity_id=entity_id,
                        error=str(exc),
                    )

            total_processed += len(rows)
            if len(rows) < host.RECONCILE_BATCH_SIZE:
                break

    def _assertion_maintenance_host(self) -> _AssertionMaintenanceHostProtocol:
        return self  # type: ignore[return-value]
