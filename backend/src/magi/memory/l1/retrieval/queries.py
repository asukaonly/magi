"""Read/query helpers for the canonical L1 event store."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, List, Literal, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...evidence import L1RetrievalScope
from ...event_contracts import MemoryDomain, MemoryEvent
from .common import FACT_EVENTS_TABLE, L1EventQueryHostProtocol
from .filters import L1EventFilterMixin
from .idempotency import L1EventIdempotencyMixin
from .maintenance import L1EventMaintenanceQueryMixin
from .timeline import L1TimelineQueryMixin


@dataclass(slots=True)
class _QueryEventsSpec:
    session_id: Optional[str]
    user_id: Optional[str]
    memory_domain: Optional[str]
    event_id: Optional[str]
    event_type: Optional[str]
    exclude_event_types: Optional[List[str]]
    query: Optional[str]
    source_filters: Optional[List[str]]
    source_item_id: Optional[str]
    idempotency_key: Optional[str]
    cognition_eligible: Optional[bool]
    start_time: Optional[float]
    end_time: Optional[float]
    exclude_memory_domain: Optional[str]
    exclude_retention_class: Optional[str]
    l1_retrieval_scopes: Optional[List[str]]
    limit: int
    offset: int
    include_metadata_json: bool
    include_embedding_fields: bool
    order_by: Literal["timestamp_desc", "timestamp_asc", "importance_desc", "created_at_desc"]

    def filter_kwargs(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "memory_domain": self.memory_domain,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "exclude_event_types": self.exclude_event_types,
            "query": self.query,
            "source_filters": self.source_filters,
            "source_item_id": self.source_item_id,
            "idempotency_key": self.idempotency_key,
            "cognition_eligible": self.cognition_eligible,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "exclude_memory_domain": self.exclude_memory_domain,
            "exclude_retention_class": self.exclude_retention_class,
            "l1_retrieval_scopes": self.l1_retrieval_scopes,
        }

    def order_clause(self) -> str:
        return {
            "timestamp_desc": "timestamp DESC",
            "timestamp_asc": "timestamp ASC",
            "importance_desc": "importance_score DESC, timestamp DESC",
            "created_at_desc": "created_at DESC, timestamp DESC",
        }.get(self.order_by, "timestamp DESC")


def _query_events_spec_from_call(raw_args: dict[str, Any]) -> _QueryEventsSpec:
    return _QueryEventsSpec(
        **{field.name: raw_args[field.name] for field in fields(_QueryEventsSpec)}
    )


class L1EventQueryMixin(
    L1EventFilterMixin,
    L1EventIdempotencyMixin,
    L1EventMaintenanceQueryMixin,
    L1TimelineQueryMixin,
):
    """SQL read, filtering, and timeline projection helpers."""

    @staticmethod
    def _select_event_columns() -> str:
        return (
            "fact_events.*, "
            "l1_event_embedding_state.embedding_status AS embedding_status, "
            "l1_event_embedding_state.embedding_profile_id AS embedding_profile_id, "
            "l1_event_embedding_state.embedding_chunk_count AS embedding_chunk_count, "
            "l1_event_embedding_state.last_embedded_at AS last_embedded_at"
        )

    async def search_events(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        domain_filters: Optional[List[str]] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
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
                l1_retrieval_scopes=l1_retrieval_scopes,
                limit=limit,
            )
            if ranked_events:
                return ranked_events

        events = await self.query_events(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            source_filters=source_filters,
            l1_retrieval_scopes=l1_retrieval_scopes,
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
                f"SELECT {self._select_event_columns()} FROM {FACT_EVENTS_TABLE} "
                "LEFT JOIN l1_event_embedding_state USING(event_id) WHERE event_id = ?",
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
                f"SELECT {self._select_event_columns()} FROM {FACT_EVENTS_TABLE} "
                "LEFT JOIN l1_event_embedding_state USING(event_id) WHERE event_id = ?",
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
        l1_retrieval_scopes: Optional[List[str]] = None,
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

        query = self._build_fetch_events_query(
            event_ids=event_ids,
            session_id=session_id,
            user_id=user_id,
            event_types=event_types,
            source_filters=source_filters,
            domain_filters=domain_filters,
            exclude_domain=exclude_domain,
            time_start=time_start,
            time_end=time_end,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        if query is None:
            return []
        sql, args = query

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        return _ordered_events(event_ids, rows, host)

    def _build_fetch_events_query(
        self,
        *,
        event_ids: List[str],
        session_id: Optional[str],
        user_id: Optional[str],
        event_types: Optional[List[str]],
        source_filters: Optional[List[str]],
        domain_filters: Optional[List[str]],
        exclude_domain: Optional[str],
        time_start: Optional[float],
        time_end: Optional[float],
        l1_retrieval_scopes: Optional[List[str]],
    ) -> tuple[str, list[Any]] | None:
        sql = (
            f"SELECT {self._select_event_columns()} FROM {FACT_EVENTS_TABLE} "
            "LEFT JOIN l1_event_embedding_state USING(event_id) "
            "WHERE deleted_at IS NULL"
        )
        args: list[Any] = []
        sql = _append_in_filter(sql, args, "event_id", event_ids)
        sql = _append_equal_filter(sql, args, "session_id", session_id)
        sql = _append_equal_filter(sql, args, "user_id", user_id)
        sql = _append_in_filter(sql, args, "event_type", event_types)
        sql = _append_in_filter(sql, args, "source", source_filters)
        scoped_sql = _append_scope_filter(sql, args, l1_retrieval_scopes)
        if scoped_sql is None:
            return None
        sql = scoped_sql
        sql = _append_domain_filters(sql, args, domain_filters, exclude_domain)
        sql = _append_time_filters(sql, args, time_start, time_end)
        return sql, args

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
        exclude_event_types: Optional[List[str]] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        order_by: Literal[
            "timestamp_desc", "timestamp_asc", "importance_desc", "created_at_desc"
        ] = "timestamp_desc",
    ) -> List[Dict[str, Any]]:
        """Query events with SQL-level filters."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        spec = _query_events_spec_from_call(locals())
        where_clause, args = self._build_event_filters(**spec.filter_kwargs())
        sql, args = self._build_query_events_sql(where_clause, args, spec)
        rows = await self._fetch_query_event_rows(host, sql, args)
        return self._query_event_rows_to_dicts(host, rows, spec)

    def _build_query_events_sql(
        self,
        where_clause: str,
        args: list[Any],
        spec: _QueryEventsSpec,
    ) -> tuple[str, list[Any]]:
        sql = (
            f"SELECT {self._select_event_columns()} FROM {FACT_EVENTS_TABLE} "
            f"LEFT JOIN l1_event_embedding_state USING(event_id) WHERE {where_clause}"
        )
        sql += f" ORDER BY {spec.order_clause()} LIMIT ? OFFSET ?"
        query_args = list(args)
        query_args.append(int(spec.limit))
        query_args.append(int(spec.offset))
        return sql, query_args

    async def _fetch_query_event_rows(
        self,
        host: L1EventQueryHostProtocol,
        sql: str,
        args: list[Any],
    ) -> list[aiosqlite.Row]:
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                return cast(list[aiosqlite.Row], await cursor.fetchall())

    @staticmethod
    def _query_event_rows_to_dicts(
        host: L1EventQueryHostProtocol,
        rows: list[aiosqlite.Row],
        spec: _QueryEventsSpec,
    ) -> List[Dict[str, Any]]:
        if spec.include_embedding_fields:
            active_embedding_profile_id, _ = host._resolve_active_embedding_profile_id()
        else:
            active_embedding_profile_id = None
        return [
            host._row_to_dict(
                row,
                include_metadata_json=spec.include_metadata_json,
                include_embedding_fields=spec.include_embedding_fields,
                active_embedding_profile_id=active_embedding_profile_id,
            )
            for row in rows
        ]

    async def query_session_event_window(
        self,
        *,
        session_id: str,
        center_session_seq: int,
        window: int,
        user_id: Optional[str] = None,
        limit: int | None = None,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch events around a session-local sequence number."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return []
        center = int(center_session_seq)
        radius = max(int(window), 0)
        start_seq = max(center - radius, 0)
        end_seq = center + radius
        row_limit = int(limit) if limit is not None else (end_seq - start_seq + 1)
        row_limit = max(row_limit, 1)

        clauses = [
            "deleted_at IS NULL",
            "session_id = ?",
            "session_seq IS NOT NULL",
            "session_seq BETWEEN ? AND ?",
        ]
        args: list[Any] = [normalized_session_id, start_seq, end_seq]
        normalized_user_id = str(user_id or "").strip()
        if normalized_user_id:
            clauses.append("user_id = ?")
            args.append(normalized_user_id)
        args.append(row_limit)

        sql = (
            f"SELECT {self._select_event_columns()} FROM {FACT_EVENTS_TABLE} "
            "LEFT JOIN l1_event_embedding_state USING(event_id) "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY session_seq ASC, timestamp ASC, id ASC "
            "LIMIT ?"
        )

        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        if include_embedding_fields:
            active_embedding_profile_id, _ = host._resolve_active_embedding_profile_id()
        else:
            active_embedding_profile_id = None
        return [
            host._row_to_dict(
                row,
                include_metadata_json=include_metadata_json,
                include_embedding_fields=include_embedding_fields,
                active_embedding_profile_id=active_embedding_profile_id,
            )
            for row in rows
        ]


def _append_equal_filter(sql: str, args: list[Any], column: str, value: str | None) -> str:
    if not value:
        return sql
    args.append(value)
    return f"{sql} AND {column} = ?"


def _append_in_filter(sql: str, args: list[Any], column: str, values: List[Any] | None) -> str:
    if not values:
        return sql
    placeholders = ", ".join("?" for _ in values)
    args.extend(values)
    return f"{sql} AND {column} IN ({placeholders})"


def _append_scope_filter(sql: str, args: list[Any], scopes: List[str] | None) -> str | None:
    if scopes is None:
        return sql
    if not scopes:
        return None
    scope_values = [int(L1RetrievalScope.from_value(scope)) for scope in scopes]
    return _append_in_filter(sql, args, "l1_retrieval_scope", scope_values)


def _append_domain_filters(
    sql: str,
    args: list[Any],
    domain_filters: List[str] | None,
    exclude_domain: str | None,
) -> str:
    if domain_filters:
        domain_ints = _memory_domain_ints(domain_filters)
        return _append_in_filter(sql, args, "memory_domain", domain_ints)
    if not exclude_domain:
        return sql
    excluded = _memory_domain_int(exclude_domain)
    if excluded is None:
        return sql
    args.append(excluded)
    return f"{sql} AND memory_domain != ?"


def _append_time_filters(
    sql: str, args: list[Any], time_start: float | None, time_end: float | None
) -> str:
    if time_start is not None:
        sql += " AND timestamp >= ?"
        args.append(time_start)
    if time_end is not None:
        sql += " AND timestamp <= ?"
        args.append(time_end)
    return sql


def _memory_domain_ints(domain_filters: List[str]) -> list[int]:
    values: list[int] = []
    for domain in domain_filters:
        domain_int = _memory_domain_int(domain)
        if domain_int is not None:
            values.append(domain_int)
    return values


def _memory_domain_int(domain: str) -> int | None:
    try:
        return int(MemoryDomain.from_value(domain))
    except (ValueError, KeyError):
        return None


def _ordered_events(
    event_ids: List[str],
    rows: list[Any],
    host: L1EventQueryHostProtocol,
) -> List[Dict[str, Any]]:
    events_by_id = {str(row["event_id"]): host._row_to_dict(row) for row in rows}
    return [events_by_id[eid] for eid in event_ids if eid in events_by_id]
