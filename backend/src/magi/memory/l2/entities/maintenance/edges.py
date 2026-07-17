"""Knowledge-graph edge lifecycle helpers for L2 entity maintenance."""

from __future__ import annotations

import time
from typing import Protocol

from .....core.sqlite import sqlite_connection_async


class _EdgeMaintenanceStatsProtocol(Protocol):
    expired_future_intents: int
    edges_archived: int
    edges_purged: int


class _EdgeMaintenanceHostProtocol(Protocol):
    _db_path: str
    ARCHIVE_CONFIDENCE_THRESHOLD: float
    ARCHIVE_STALENESS_SECONDS: float
    ARCHIVE_SINGLE_OBS_STALENESS: float
    PURGE_TERMINAL_EDGE_STALENESS: float

    async def _clean_non_active_edge_embeddings(
        self,
        stats: _EdgeMaintenanceStatsProtocol,
    ) -> None: ...


class L2EntityEdgeMaintenanceMixin:
    """Maintain edge expiry, archival, and terminal purging."""

    async def _expire_stale_future_intents(
        self,
        stats: _EdgeMaintenanceStatsProtocol,
    ) -> None:
        """Mark expired future_intent edges as 'expired'."""
        host = self._edge_maintenance_host()
        now = time.time()
        async with sqlite_connection_async(host._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'expired', updated_at = ?
                WHERE fact_kind = 'future_intent'
                  AND expires_at IS NOT NULL AND expires_at < ?
                  AND status = 'active'
                """,
                (now, now),
            )
            stats.expired_future_intents = cursor.rowcount
            await db.commit()

    async def _archive_stale_edges(
        self,
        stats: _EdgeMaintenanceStatsProtocol,
    ) -> None:
        """Move low-confidence stale edges from 'active' to 'archived'."""
        host = self._edge_maintenance_host()
        now = time.time()
        cutoff_low_conf = now - host.ARCHIVE_STALENESS_SECONDS
        cutoff_single_obs = now - host.ARCHIVE_SINGLE_OBS_STALENESS

        async with sqlite_connection_async(host._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'archived', updated_at = ?
                WHERE status = 'active'
                  AND fact_kind != 'future_intent'
                  AND (valid_from IS NULL OR valid_from <= ?)
                  AND TRIM(COALESCE(authority_ref, '')) = ''
                  AND LOWER(TRIM(COALESCE(evidence_class, ''))) != 'user_self_report'
                  AND LOWER(TRIM(COALESCE(source_type, ''))) != 'user_correction'
                  AND (
                      (confidence < ? AND updated_at < ?)
                      OR
                      (observation_count = 1 AND updated_at < ?)
                  )
                """,
                (
                    now,
                    now,
                    host.ARCHIVE_CONFIDENCE_THRESHOLD,
                    cutoff_low_conf,
                    cutoff_single_obs,
                ),
            )
            archived = cursor.rowcount
            if archived:
                await db.commit()
            stats.edges_archived = archived

        await host._clean_non_active_edge_embeddings(stats)

    async def _purge_terminal_edges(
        self,
        stats: _EdgeMaintenanceStatsProtocol,
    ) -> None:
        """Hard-delete archived/expired edges older than PURGE_TERMINAL_EDGE_STALENESS."""
        host = self._edge_maintenance_host()
        now = time.time()
        cutoff = now - host.PURGE_TERMINAL_EDGE_STALENESS
        async with sqlite_connection_async(host._db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM knowledge_graph
                WHERE status IN ('archived', 'expired')
                  AND updated_at < ?
                """,
                (cutoff,),
            )
            purged = cursor.rowcount
            if purged:
                await db.commit()
            stats.edges_purged = purged

    def _edge_maintenance_host(self) -> _EdgeMaintenanceHostProtocol:
        return self  # type: ignore[return-value]
