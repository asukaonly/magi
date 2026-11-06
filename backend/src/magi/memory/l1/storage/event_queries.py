"""SQLite query owner for canonical events and their evidence identities."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Dict, List, Optional

import aiosqlite

from .connection import event_connection
from ...evidence import L1RetrievalScope
from ...event_contracts import MemoryDomain, author_type_label
from ..ports import EventEvidenceReference, EventQuery, EventSourceIdentity, MemoryEventRecord
from .event_filters import L1EventFilterMixin
from .event_mapping import decode_event_metadata, event_record_from_mapping
from ..overview_contracts import EventOverview, EventOverviewQuery
from .event_overview import read_event_overview

FACT_EVENTS_TABLE = "fact_events"


def select_event_columns() -> str:
    return (
        "fact_events.*, "
        "l1_event_embedding_state.embedding_status AS embedding_status, "
        "l1_event_embedding_state.embedding_profile_id AS embedding_profile_id, "
        "l1_event_embedding_state.embedding_chunk_count AS embedding_chunk_count, "
        "l1_event_embedding_state.last_embedded_at AS last_embedded_at"
    )


def _record(row: aiosqlite.Row, *, include_metadata: bool = True) -> MemoryEventRecord:
    values = dict(row)
    if not include_metadata:
        values["metadata_json"] = None
    return event_record_from_mapping(values)


class SqliteEventQueries:
    _db_path: str

    async def read_event_overview(self, query: EventOverviewQuery) -> EventOverview:
        return await read_event_overview(self._db_path, query)

    async def get_event_timestamps(self, event_ids: List[str]) -> Dict[str, float]:
        """Return original occurrence timestamps for existing, active L1 events."""
        ordered_ids = list(dict.fromkeys(str(event_id) for event_id in event_ids if event_id))
        if not ordered_ids:
            return {}
        timestamps: Dict[str, float] = {}
        async with event_connection(self._db_path) as db:
            for offset in range(0, len(ordered_ids), 500):
                chunk = ordered_ids[offset : offset + 500]
                placeholders = ", ".join("?" for _ in chunk)
                async with db.execute(
                    f"SELECT event_id, timestamp FROM {FACT_EVENTS_TABLE} "
                    f"WHERE deleted_at IS NULL AND event_id IN ({placeholders})",
                    tuple(chunk),
                ) as cursor:
                    for event_id, timestamp in await cursor.fetchall():
                        timestamps[str(event_id)] = float(timestamp)
        return timestamps


    async def get_evidence_records(self, event_ids: List[str]) -> dict[str, EventEvidenceReference]:
        """Read active source identity and semantics in bounded batches for evidence checks."""
        ids = list(dict.fromkeys(str(value) for value in event_ids if value))
        result: dict[str, EventEvidenceReference] = {}
        async with event_connection(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            for offset in range(0, len(ids), 500):
                chunk = ids[offset:offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                async with db.execute(
                    f"SELECT event_id, timestamp, source, source_item_id, content, author_type, event_type, metadata_json FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL AND event_id IN ({placeholders})",
                    tuple(chunk),
                ) as cursor:
                    for row in await cursor.fetchall():
                        result[str(row["event_id"])] = EventEvidenceReference(
                            event_id=str(row["event_id"]), timestamp=float(row["timestamp"]),
                            source=str(row["source"]), source_item_id=row["source_item_id"],
                            content=str(row["content"]), event_type=str(row["event_type"]),
                            author_type=author_type_label(row["author_type"]),
                            metadata_json=decode_event_metadata(row["metadata_json"]) or {},
                        )
        return result


    async def get_raw_event_turn_ids(self, event_ids: List[str]) -> Dict[str, str]:
        """Return turn IDs for existing events, including soft-deleted rows.

        This maintenance reader intentionally bypasses active and user-visible
        filters so source-event forgetting can be retried after L1 was hidden.
        """
        ordered_ids = list(dict.fromkeys(str(event_id) for event_id in event_ids if event_id))
        if not ordered_ids:
            return {}
        fetched_turn_ids: Dict[str, str] = {}
        async with event_connection(self._db_path) as db:
            for offset in range(0, len(ordered_ids), 500):
                chunk = ordered_ids[offset : offset + 500]
                placeholders = ", ".join("?" for _ in chunk)
                async with db.execute(
                    f"SELECT event_id, turn_id FROM {FACT_EVENTS_TABLE} "
                    f"WHERE event_id IN ({placeholders})",
                    tuple(chunk),
                ) as cursor:
                    for event_id, turn_id in await cursor.fetchall():
                        normalized_turn_id = str(turn_id or "").strip()
                        if normalized_turn_id:
                            fetched_turn_ids[str(event_id)] = normalized_turn_id
        return {
            event_id: fetched_turn_ids[event_id]
            for event_id in ordered_ids
            if event_id in fetched_turn_ids
        }


    async def get_raw_event_source_identities(
        self,
        event_ids: List[str],
    ) -> dict[str, EventSourceIdentity]:
        """Return replay and turn identities, including soft-deleted rows."""
        ordered_ids = list(dict.fromkeys(str(event_id) for event_id in event_ids if event_id))
        if not ordered_ids:
            return {}
        fetched: dict[str, EventSourceIdentity] = {}
        async with event_connection(self._db_path) as db:
            for offset in range(0, len(ordered_ids), 500):
                chunk = ordered_ids[offset : offset + 500]
                placeholders = ", ".join("?" for _ in chunk)
                async with db.execute(
                    f"""
                    SELECT event_id, event_type, source, source_item_id,
                           idempotency_key, turn_id, session_id, user_id, deleted_at
                    FROM {FACT_EVENTS_TABLE}
                    WHERE event_id IN ({placeholders})
                    """,
                    tuple(chunk),
                ) as cursor:
                    for row in await cursor.fetchall():
                        fetched[str(row[0])] = {
                            "event_type": str(row[1] or "").strip() or None,
                            "source": str(row[2] or "").strip() or None,
                            "source_item_id": str(row[3] or "").strip() or None,
                            "idempotency_key": str(row[4] or "").strip() or None,
                            "turn_id": str(row[5] or "").strip() or None,
                            "session_id": str(row[6] or "").strip() or None,
                            "user_id": str(row[7] or "").strip() or None,
                            "was_active": row[8] is None,
                        }
        return {event_id: fetched[event_id] for event_id in ordered_ids if event_id in fetched}


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
    ) -> list[MemoryEventRecord]:
        """Hydrate events by IDs with optional SQL filters, preserving input order.

        Parameters mirror the filtering logic used by hybrid retrieval handlers.
        *exclude_domain* defaults to ``RUNTIME_TELEMETRY`` when *domain_filters*
        is not provided.
        """
        if not event_ids:
            return []

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

        async with event_connection(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        records = {str(row["event_id"]): _record(row) for row in rows}
        return [records[event_id] for event_id in event_ids if event_id in records]


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
            f"SELECT {select_event_columns()} FROM {FACT_EVENTS_TABLE} "
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


    async def query_session_event_window(
        self,
        *,
        session_id: str,
        center_session_seq: int,
        window: int,
        user_id: Optional[str] = None,
        limit: int | None = None,
        include_metadata_json: bool = True,
    ) -> list[MemoryEventRecord]:
        """Fetch events around a session-local sequence number."""
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
            f"SELECT {select_event_columns()} FROM {FACT_EVENTS_TABLE} "
            "LEFT JOIN l1_event_embedding_state USING(event_id) "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY session_seq ASC, timestamp ASC, id ASC "
            "LIMIT ?"
        )

        async with event_connection(self._db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [_record(row, include_metadata=include_metadata_json) for row in rows]

    async def query_events(self, query: EventQuery) -> list[MemoryEventRecord]:
        filters = {
            field.name: getattr(query, field.name)
            for field in fields(query)
            if field.name not in {"limit", "offset", "include_metadata_json", "order_by"}
        }
        where, args = L1EventFilterMixin._build_event_filters(**filters)
        order = {
            "timestamp_desc": "timestamp DESC", "timestamp_asc": "timestamp ASC",
            "importance_desc": "importance_score DESC, timestamp DESC",
            "created_at_desc": "created_at DESC, timestamp DESC",
        }.get(query.order_by, "timestamp DESC")
        sql = (
            f"SELECT {select_event_columns()} FROM fact_events "
            f"LEFT JOIN l1_event_embedding_state USING(event_id) WHERE {where} "
            f"ORDER BY {order} LIMIT ? OFFSET ?"
        )
        async with event_connection(self._db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, (*args, int(query.limit), int(query.offset))) as cursor:
                rows = await cursor.fetchall()
        return [_record(row, include_metadata=query.include_metadata_json) for row in rows]


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
