"""Read/query helpers for the canonical L1 event store."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...event_contracts import MemoryDomain, MemoryEvent, RetentionClass

FACT_EVENTS_TABLE = "fact_events"


class _L1EventQueryHostProtocol(Protocol):
    db_path: str
    _vector_index: Any

    async def initialize(self) -> None: ...

    def _row_to_dict(
        self,
        row: aiosqlite.Row,
        *,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        active_embedding_profile_id: str | None = None,
    ) -> Dict[str, Any]: ...

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent: ...

    async def _semantic_search_event_hits(
        self, *, query: str, limit: int, user_id: str | None = None
    ) -> list[Any]: ...

    async def _fetch_ranked_events(
        self,
        *,
        hits: list[Any],
        session_id: Optional[str],
        user_id: Optional[str],
        event_type: Optional[str],
        source_filters: Optional[List[str]],
        domain_filters: Optional[List[str]],
        limit: int,
    ) -> List[Dict[str, Any]]: ...

    def _chunk_id_for_event(self, event_id: str, chunk_index: int) -> str: ...

    def _resolve_active_embedding_profile_id(self) -> tuple[str | None, dict[str, Any]]: ...

    def _to_timeline_view(self, event: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]: ...


class L1EventQueryMixin:
    """SQL read, filtering, and timeline projection helpers."""

    async def search_events(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        domain_filters: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search L1 events using sqlite-vec and fall back to keyword matching."""
        host = cast(_L1EventQueryHostProtocol, self)
        semantic_hits = await host._semantic_search_event_hits(
            query=query, limit=max(limit * 5, 20)
        )
        if semantic_hits:
            ranked_events = await host._fetch_ranked_events(
                hits=semantic_hits,
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                source_filters=source_filters,
                domain_filters=domain_filters,
                limit=limit,
            )
            if ranked_events:
                return ranked_events

        events = await self.query_events(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            source_filters=source_filters,
            limit=max(limit * 5, 20),
        )
        allowed_domains = {MemoryDomain.from_value(value).label for value in domain_filters or []}
        query_tokens = [token for token in query.lower().split() if token]
        filtered = [
            event
            for event in events
            if event["memory_domain"] != MemoryDomain.RUNTIME_TELEMETRY.label
            and (not allowed_domains or event["memory_domain"] in allowed_domains)
            and all(token in event["content"].lower() for token in query_tokens)
        ]
        return filtered[:limit]

    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single event by id."""
        host = cast(_L1EventQueryHostProtocol, self)
        await host.initialize()
        try:
            active_embedding_profile_id, _ = host._resolve_active_embedding_profile_id()
        except Exception:
            active_embedding_profile_id = None
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return (
            host._row_to_dict(row, active_embedding_profile_id=active_embedding_profile_id)
            if row
            else None
        )

    async def get_memory_event(self, event_id: str) -> Optional[MemoryEvent]:
        """Fetch a single event as the canonical MemoryEvent contract."""
        host = cast(_L1EventQueryHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return host._row_to_memory_event(row) if row else None

    async def get_event_vectors(
        self,
        event_ids: List[str],
    ) -> Dict[str, List[float]]:
        """Return embedding vectors for the given event IDs.

        For each event, returns the chunk-0 embedding (primary chunk).
        Events without embeddings are silently omitted.
        """
        host = cast(_L1EventQueryHostProtocol, self)
        if not event_ids or host._vector_index is None:
            return {}
        chunk_ids = [host._chunk_id_for_event(eid, 0) for eid in event_ids]
        raw = await host._vector_index.get_vectors(entity_ids=chunk_ids)
        result: Dict[str, List[float]] = {}
        for eid in event_ids:
            cid = host._chunk_id_for_event(eid, 0)
            if cid in raw:
                result[eid] = raw[cid]
        return result

    async def fetch_events(
        self,
        event_ids: List[str],
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        source_filters: Optional[List[str]] = None,
        domain_filters: Optional[List[str]] = None,
        exclude_domain: Optional[str] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Hydrate events by IDs with optional SQL filters, preserving input order.

        Parameters mirror the filtering logic used by hybrid retrieval handlers.
        *exclude_domain* defaults to ``RUNTIME_TELEMETRY`` when *domain_filters*
        is not provided.
        """
        host = cast(_L1EventQueryHostProtocol, self)
        if not event_ids:
            return []
        await host.initialize()

        sql = "SELECT * FROM fact_events WHERE deleted_at IS NULL"
        args: list[Any] = []
        ph = ", ".join("?" for _ in event_ids)
        sql += f" AND event_id IN ({ph})"
        args.extend(event_ids)

        if session_id:
            sql += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            sql += " AND user_id = ?"
            args.append(user_id)
        if event_types:
            et_ph = ", ".join("?" for _ in event_types)
            sql += f" AND event_type IN ({et_ph})"
            args.extend(event_types)
        if source_filters:
            sf_ph = ", ".join("?" for _ in source_filters)
            sql += f" AND source IN ({sf_ph})"
            args.extend(source_filters)

        if domain_filters:
            domain_ints: list[int] = []
            for df in domain_filters:
                try:
                    domain_ints.append(int(MemoryDomain.from_value(df)))
                except (ValueError, KeyError):
                    pass
            if domain_ints:
                df_ph = ", ".join("?" for _ in domain_ints)
                sql += f" AND memory_domain IN ({df_ph})"
                args.extend(domain_ints)
        elif exclude_domain:
            try:
                sql += " AND memory_domain != ?"
                args.append(int(MemoryDomain.from_value(exclude_domain)))
            except (ValueError, KeyError):
                pass

        if time_start is not None:
            sql += " AND timestamp >= ?"
            args.append(time_start)
        if time_end is not None:
            sql += " AND timestamp <= ?"
            args.append(time_end)

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        events_by_id = {str(row["event_id"]): host._row_to_dict(row) for row in rows}
        return [events_by_id[eid] for eid in event_ids if eid in events_by_id]

    async def find_event_id_by_idempotency(
        self,
        *,
        source: str,
        event_type: str,
        idempotency_key: str | None,
    ) -> Optional[str]:
        """Find an existing event id by business idempotency tuple."""
        host = cast(_L1EventQueryHostProtocol, self)
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

    async def list_events(
        self, *, limit: int = 100, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List the newest events, optionally constrained by event type."""
        return await self.query_events(event_type=event_type, limit=limit)

    async def query_events(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_domain: Optional[str] = None,
        event_type: Optional[str] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        order_by: Literal["timestamp_desc", "timestamp_asc", "importance_desc"] = "timestamp_desc",
    ) -> List[Dict[str, Any]]:
        """Query events with SQL-level filters."""
        host = cast(_L1EventQueryHostProtocol, self)
        await host.initialize()
        where_clause, args = self._build_event_filters(
            session_id=session_id,
            user_id=user_id,
            memory_domain=memory_domain,
            event_type=event_type,
            query=query,
            source_filters=source_filters,
            source_item_id=source_item_id,
            idempotency_key=idempotency_key,
            cognition_eligible=cognition_eligible,
            start_time=start_time,
            end_time=end_time,
            exclude_memory_domain=exclude_memory_domain,
            exclude_retention_class=exclude_retention_class,
        )
        sql = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE {where_clause}"
        order_clause = {
            "timestamp_desc": "timestamp DESC",
            "timestamp_asc": "timestamp ASC",
            "importance_desc": "importance_score DESC, timestamp DESC",
        }.get(order_by, "timestamp DESC")
        sql += f" ORDER BY {order_clause} LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        if include_embedding_fields:
            active_embedding_profile_id, _ = host._resolve_active_embedding_profile_id()
        else:
            active_embedding_profile_id = None
        items = [
            host._row_to_dict(
                row,
                include_metadata_json=include_metadata_json,
                include_embedding_fields=include_embedding_fields,
                active_embedding_profile_id=active_embedding_profile_id,
            )
            for row in rows
        ]
        return items

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
        host = cast(_L1EventQueryHostProtocol, self)
        await host.initialize()
        where_clause, args = self._build_event_filters(
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
                "min_timestamp": float(row["min_timestamp"])
                if row["min_timestamp"] is not None
                else None,
                "max_timestamp": float(row["max_timestamp"])
                if row["max_timestamp"] is not None
                else None,
            }
            for row in rows
            if str(row["source"] or "").strip()
        ]

    @staticmethod
    def _build_event_filters(
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_domain: Optional[str] = None,
        event_type: Optional[str] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
    ) -> tuple[str, List[Any]]:
        """Build WHERE clause and args for event queries."""
        parts = ["deleted_at IS NULL"]
        args: List[Any] = []
        if session_id:
            parts.append("session_id = ?")
            args.append(session_id)
        if user_id:
            parts.append("user_id = ?")
            args.append(user_id)
        if memory_domain:
            parts.append("memory_domain = ?")
            args.append(int(MemoryDomain.from_value(memory_domain)))
        if event_type:
            parts.append("event_type = ?")
            args.append(event_type)
        if query:
            parts.append("LOWER(content) LIKE ?")
            args.append(f"%{str(query).strip().lower()}%")
        if source_filters:
            placeholders = ", ".join("?" for _ in source_filters)
            parts.append(f"source IN ({placeholders})")
            args.extend(source_filters)
        if source_item_id:
            parts.append("source_item_id = ?")
            args.append(source_item_id)
        if idempotency_key:
            parts.append("idempotency_key = ?")
            args.append(idempotency_key)
        if cognition_eligible is not None:
            parts.append("cognition_eligible = ?")
            args.append(1 if cognition_eligible else 0)
        if start_time is not None:
            parts.append("timestamp >= ?")
            args.append(float(start_time))
        if end_time is not None:
            parts.append("timestamp <= ?")
            args.append(float(end_time))
        if exclude_memory_domain:
            try:
                parts.append("memory_domain != ?")
                args.append(int(MemoryDomain.from_value(exclude_memory_domain)))
            except (ValueError, KeyError):
                pass
        if exclude_retention_class:
            try:
                parts.append("retention_class != ?")
                args.append(int(RetentionClass.from_value(exclude_retention_class)))
            except (ValueError, KeyError):
                pass
        return " AND ".join(parts), args

    async def get_timeline_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Return a minimal timeline-shaped view from canonical L1 columns."""
        host = cast(_L1EventQueryHostProtocol, self)
        event = await self.get_event(event_id)
        return host._to_timeline_view(event)

    async def list_timeline_events(
        self, *, limit: int = 100, source_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List timeline-shaped views with optional source filtering."""
        host = cast(_L1EventQueryHostProtocol, self)
        events = await self.query_events(limit=max(limit * 10, limit))
        items: List[Dict[str, Any]] = []
        for event in events:
            item = host._to_timeline_view(event)
            if item is None:
                continue
            if source_type and item["source_type"] != source_type:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    async def count_events(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        """Count events, optionally filtered."""
        host = cast(_L1EventQueryHostProtocol, self)
        await host.initialize()
        where_clause, args = self._build_event_filters(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            query=query,
            source_filters=source_filters,
            source_item_id=source_item_id,
            idempotency_key=idempotency_key,
            start_time=start_time,
            end_time=end_time,
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
        host = cast(_L1EventQueryHostProtocol, self)
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
