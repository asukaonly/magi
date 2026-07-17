"""Maintenance and reporting queries for L1 event retrieval."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...event_contracts import RetentionClass
from .common import FACT_EVENTS_TABLE, L1EventQueryHostProtocol


class L1EventMaintenanceQueryMixin:
    """Source summaries, counts, and compaction candidate queries."""

    async def summarize_event_sources(
        self,
        *,
        source_filters: Optional[List[str]] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return lightweight source counts for a filtered L1 event window."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        where_clause, args = host._build_event_filters(
            source_filters=source_filters,
            cognition_eligible=cognition_eligible,
            start_time=start_time,
            end_time=end_time,
            exclude_memory_domain=exclude_memory_domain,
            exclude_retention_class=exclude_retention_class,
        )
        sql = f"""
            SELECT
                source,
                COUNT(*) AS event_count,
                AVG(importance_score) AS avg_importance,
                MIN(timestamp) AS min_timestamp,
                MAX(timestamp) AS max_timestamp
            FROM {FACT_EVENTS_TABLE}
            WHERE {where_clause}
            GROUP BY source
            ORDER BY event_count DESC, source ASC
        """
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "source": str(row["source"] or ""),
                "event_count": int(row["event_count"] or 0),
                "avg_importance": float(row["avg_importance"] or 0.0),
                "min_timestamp": (
                    float(row["min_timestamp"]) if row["min_timestamp"] is not None else None
                ),
                "max_timestamp": (
                    float(row["max_timestamp"]) if row["max_timestamp"] is not None else None
                ),
            }
            for row in rows
            if str(row["source"] or "").strip()
        ]

    async def count_events(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_id: Optional[str] = None,
        event_type: Optional[str] = None,
        exclude_event_types: Optional[List[str]] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> int:
        """Count events, optionally filtered."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        where_clause, args = host._build_event_filters(
            session_id=session_id,
            user_id=user_id,
            event_id=event_id,
            event_type=event_type,
            exclude_event_types=exclude_event_types,
            query=query,
            source_filters=source_filters,
            source_item_id=source_item_id,
            idempotency_key=idempotency_key,
            start_time=start_time,
            end_time=end_time,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        sql = f"SELECT COUNT(*) FROM {FACT_EVENTS_TABLE} WHERE {where_clause}"
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            async with db.execute(sql, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_compressible_event_ids(
        self,
        *,
        older_than: float,
        limit: int = 1000,
    ) -> List[str]:
        """List non-deleted compressible L1 events older than a cutoff timestamp."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            async with db.execute(
                f"""
                SELECT event_id
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND retention_class = ?
                  AND timestamp < ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (
                    int(RetentionClass.COMPRESSIBLE),
                    float(older_than),
                    int(limit),
                ),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]


__all__ = ["L1EventMaintenanceQueryMixin"]
