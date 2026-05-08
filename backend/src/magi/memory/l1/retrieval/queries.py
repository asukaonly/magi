"""Read/query helpers for the canonical L1 event store."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...event_contracts import MemoryDomain, MemoryEvent
from .common import FACT_EVENTS_TABLE, L1EventQueryHostProtocol
from .filters import L1EventFilterMixin
from .idempotency import L1EventIdempotencyMixin
from .maintenance import L1EventMaintenanceQueryMixin
from .timeline import L1TimelineQueryMixin


class L1EventQueryMixin(
    L1EventFilterMixin,
    L1EventIdempotencyMixin,
    L1EventMaintenanceQueryMixin,
    L1TimelineQueryMixin,
):
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
        host = cast(L1EventQueryHostProtocol, self)
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
        host = cast(L1EventQueryHostProtocol, self)
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
        host = cast(L1EventQueryHostProtocol, self)
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
        host = cast(L1EventQueryHostProtocol, self)
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
        host = cast(L1EventQueryHostProtocol, self)
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
        event_id: Optional[str] = None,
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
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        where_clause, args = self._build_event_filters(
            session_id=session_id,
            user_id=user_id,
            memory_domain=memory_domain,
            event_id=event_id,
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
