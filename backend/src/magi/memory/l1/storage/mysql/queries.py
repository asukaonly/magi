"""SQLAlchemy expressions for bounded MySQL event reads."""

from __future__ import annotations

from .common import MysqlEventConnection

from sqlalchemy import false, func, select
from magi.memory.event_contracts import MemoryDomain, RetentionClass
from magi.memory.evidence import L1RetrievalScope
from ...ports import EventEvidenceReference, EventQuery, EventSourceIdentity, MemoryEventRecord
from .common import event_select, identity, record
from .schema import events as e
from ...overview_contracts import EventOverview, EventOverviewQuery
from .overview import read_event_overview


def filters(query: EventQuery) -> list:
    parts = [e.c.deleted_at.is_(None)]
    for name in (
        "session_id",
        "user_id",
        "event_id",
        "event_type",
        "source_item_id",
        "idempotency_key",
    ):
        value = getattr(query, name)
        if value:
            parts.append(e.c[name] == value)
            key_name = {
                "session_id": "session_key",
                "user_id": "user_key",
                "event_id": "event_key",
            }.get(name)
            if key_name:
                parts.append(e.c[key_name] == identity(value))
    if query.memory_domain:
        parts.append(e.c.memory_domain == int(MemoryDomain.from_value(query.memory_domain)))
    if query.exclude_event_types:
        parts.append(e.c.event_type.not_in(query.exclude_event_types))
    if query.query:
        parts.append(func.lower(e.c.content).like("%" + query.query.strip().lower() + "%"))
    if query.source_filters:
        parts.extend(
            (
                e.c.source_key.in_([identity(v) for v in query.source_filters]),
                e.c.source.in_(query.source_filters),
            )
        )
    if query.cognition_eligible is not None:
        parts.append(e.c.cognition_eligible == int(query.cognition_eligible))
    if query.start_time is not None:
        parts.append(e.c.timestamp >= query.start_time)
    if query.end_time is not None:
        parts.append(e.c.timestamp <= query.end_time)
    for value, column, enum in (
        (query.exclude_memory_domain, e.c.memory_domain, MemoryDomain),
        (query.exclude_retention_class, e.c.retention_class, RetentionClass),
    ):
        if value:
            parts.append(column != int(enum.from_value(value)))
    if query.l1_retrieval_scopes is not None:
        parts.append(
            e.c.l1_retrieval_scope.in_(
                [int(L1RetrievalScope.from_value(v)) for v in query.l1_retrieval_scopes]
            )
            if query.l1_retrieval_scopes
            else false()
        )
    return parts


class MysqlEventQueries(MysqlEventConnection):
    async def read_event_overview(self, query: EventOverviewQuery) -> EventOverview:
        async with self._transaction() as connection:
            return await read_event_overview(connection, query)

    async def query_events(self, query: EventQuery) -> list[MemoryEventRecord]:
        order = {
            "timestamp_desc": (e.c.timestamp.desc(),),
            "timestamp_asc": (e.c.timestamp.asc(),),
            "importance_desc": (e.c.importance_score.desc(), e.c.timestamp.desc()),
            "created_at_desc": (e.c.created_at.desc(), e.c.timestamp.desc()),
        }[query.order_by]
        async with self._transaction() as connection:
            rows = (
                (
                    await connection.execute(
                        event_select()
                        .where(*filters(query))
                        .order_by(*order, e.c.id)
                        .limit(query.limit)
                        .offset(query.offset)
                    )
                )
                .mappings()
                .all()
            )
        return [record(row, include_metadata=query.include_metadata_json) for row in rows]

    async def count_events(self, **options) -> int:
        async with self._transaction() as connection:
            return int(
                (
                    await connection.execute(
                        select(func.count()).select_from(e).where(*filters(EventQuery(**options)))
                    )
                ).scalar_one()
            )

    async def _records_by_ids(
        self, event_ids: list[str], *, active: bool = False
    ) -> dict[str, MemoryEventRecord]:
        result = {}
        ids = list(dict.fromkeys(v for v in event_ids if v))
        async with self._transaction() as connection:
            for offset in range(0, len(ids), 500):
                page = ids[offset : offset + 500]
                query = event_select().where(
                    e.c.event_key.in_([identity(v) for v in page]), e.c.event_id.in_(page)
                )
                if active:
                    query = query.where(e.c.deleted_at.is_(None))
                for row in (await connection.execute(query)).mappings():
                    result[row["event_id"]] = record(row)
        return result

    async def get_event_timestamps(self, event_ids: list[str]) -> dict[str, float]:
        return {
            key: row.event.timestamp
            for key, row in (await self._records_by_ids(event_ids, active=True)).items()
        }

    async def get_evidence_records(self, event_ids: list[str]) -> dict[str, EventEvidenceReference]:
        return {
            key: EventEvidenceReference(
                event_id=key,
                timestamp=row.event.timestamp,
                source=row.event.source,
                source_item_id=row.event.source_item_id,
                content=row.event.content,
                author_type=row.event.author_type,
                event_type=row.event.event_type,
                metadata_json=row.event.metadata_json or {},
            )
            for key, row in (await self._records_by_ids(event_ids, active=True)).items()
        }

    async def get_raw_event_turn_ids(self, event_ids: list[str]) -> dict[str, str]:
        return {
            key: row.event.turn_id.strip()
            for key, row in (await self._records_by_ids(event_ids)).items()
            if row.event.turn_id and row.event.turn_id.strip()
        }

    async def get_raw_event_source_identities(
        self, event_ids: list[str]
    ) -> dict[str, EventSourceIdentity]:
        result = {}
        for key, row in (await self._records_by_ids(event_ids)).items():
            event = row.event
            result[key] = EventSourceIdentity(
                event_type=str(event.event_type or "").strip() or None,
                source=str(event.source or "").strip() or None,
                source_item_id=str(event.source_item_id or "").strip() or None,
                idempotency_key=str(event.idempotency_key or "").strip() or None,
                turn_id=str(event.turn_id or "").strip() or None,
                session_id=str(event.session_id or "").strip() or None,
                user_id=str(event.user_id or "").strip() or None,
                was_active=row.deleted_at is None,
            )
        return result

    async def fetch_events(
        self,
        event_ids: list[str],
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        event_types: list[str] | None = None,
        source_filters: list[str] | None = None,
        domain_filters: list[str] | None = None,
        exclude_domain: str | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        l1_retrieval_scopes: list[str] | None = None,
    ) -> list[MemoryEventRecord]:
        conditions = filters(
            EventQuery(
                session_id=session_id,
                user_id=user_id,
                source_filters=source_filters,
                start_time=time_start,
                end_time=time_end,
                l1_retrieval_scopes=l1_retrieval_scopes,
                exclude_memory_domain=exclude_domain if not domain_filters else None,
            )
        )
        if domain_filters:
            conditions.append(
                e.c.memory_domain.in_([int(MemoryDomain.from_value(v)) for v in domain_filters])
            )
        if event_types:
            conditions.append(e.c.event_type.in_(event_types))
        records = {}
        async with self._transaction() as connection:
            for offset in range(0, len(event_ids), 500):
                page = event_ids[offset : offset + 500]
                rows = (
                    await connection.execute(
                        event_select().where(
                            *conditions,
                            e.c.event_key.in_([identity(v) for v in page]),
                            e.c.event_id.in_(page),
                        )
                    )
                ).mappings()
                records.update({row["event_id"]: record(row) for row in rows})
        return [records[value] for value in event_ids if value in records]

    async def query_session_event_window(
        self,
        *,
        session_id: str,
        center_session_seq: int,
        window: int,
        user_id: str | None = None,
        limit: int | None = None,
        include_metadata_json: bool = True,
    ) -> list[MemoryEventRecord]:
        if not session_id.strip():
            return []
        start = max(int(center_session_seq) - max(int(window), 0), 0)
        end = int(center_session_seq) + max(int(window), 0)
        query = (
            event_select()
            .where(
                *filters(EventQuery(session_id=session_id.strip(), user_id=user_id)),
                e.c.session_seq.between(start, end),
            )
            .order_by(e.c.session_seq, e.c.timestamp, e.c.id)
            .limit(max(1, limit if limit is not None else end - start + 1))
        )
        async with self._transaction() as connection:
            return [
                record(row, include_metadata=include_metadata_json)
                for row in (await connection.execute(query)).mappings()
            ]
