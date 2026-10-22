"""MySQL facet projections and source-checked rebuilding."""

from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any

from sqlalchemy import delete, func, insert, select

from ...ports import EventQuery, MemoryEventRecord
from ...source_facets import SourceFacet, extract_source_facets
from .common import event_select, identity, nullable_identity, record
from .queries import filters
from . import schema as s


def facet_values(facet: SourceFacet) -> dict[str, Any]:
    return {
        **asdict(facet),
        "created_at": facet.created_at or time.time(),
        "event_key": identity(facet.event_id),
        "source_key": identity(facet.source),
        "facet_key": identity(facet.facet_name),
        "text_key": nullable_identity(facet.normalized_text_value),
    }


def facet_filters(
    *,
    event_id: str | None = None,
    source: str | None = None,
    sources: list[str] | None = None,
    facet_names: list[str] | None = None,
    normalized_text_values: list[str] | None = None,
) -> list:
    conditions = []
    for value, name, key in ((event_id, "event_id", "event_key"), (source, "source", "source_key")):
        if value:
            conditions.extend((s.facets.c[name] == value, s.facets.c[key] == identity(value)))
    for values, name, key in (
        (sources, "source", "source_key"),
        (facet_names, "facet_name", "facet_key"),
        (normalized_text_values, "normalized_text_value", "text_key"),
    ):
        if values:
            conditions.extend(
                (s.facets.c[name].in_(values), s.facets.c[key].in_([identity(v) for v in values]))
            )
    return conditions


class MysqlEventFacets:
    async def list_source_facets(
        self,
        *,
        event_id: str | None = None,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str] | None = None,
        normalized_text_values: list[str] | None = None,
        limit: int = 1000,
    ) -> list[SourceFacet]:
        columns = [s.facets.c[name] for name in SourceFacet.__dataclass_fields__]
        query = (
            select(*columns)
            .where(
                *facet_filters(
                    event_id=event_id,
                    source=source,
                    sources=sources,
                    facet_names=facet_names,
                    normalized_text_values=normalized_text_values,
                )
            )
            .order_by(
                s.facets.c.event_id,
                s.facets.c.facet_name,
                s.facets.c.text_value,
            )
            .limit(max(1, int(limit)))
        )
        async with self._transaction() as connection:
            return [
                SourceFacet(**dict(row)) for row in (await connection.execute(query)).mappings()
            ]

    async def count_source_facets(
        self,
        *,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str] | None = None,
    ) -> int:
        async with self._transaction() as connection:
            return int(
                (
                    await connection.execute(
                        select(func.count())
                        .select_from(s.facets)
                        .where(
                            *facet_filters(source=source, sources=sources, facet_names=facet_names),
                        )
                    )
                ).scalar_one()
            )

    async def find_events_by_source_facets(
        self,
        *,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str],
        normalized_text_values: list[str],
        user_id: str | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        limit: int = 1000,
    ) -> list[MemoryEventRecord]:
        source_values = list(dict.fromkeys(v for v in [*(sources or []), source] if v))
        text_values = [v for v in normalized_text_values if v]
        if not source_values or not text_values or not facet_names:
            return []
        candidates = select(s.facets.c.event_key).where(
            *facet_filters(
                sources=source_values, facet_names=facet_names, normalized_text_values=text_values
            )
        )
        query = (
            event_select()
            .where(
                *filters(EventQuery(user_id=user_id, start_time=time_start, end_time=time_end)),
                s.events.c.event_key.in_(candidates),
            )
            .order_by(s.events.c.timestamp, s.events.c.id)
            .limit(max(1, int(limit)))
        )
        async with self._transaction() as connection:
            return [record(row) for row in (await connection.execute(query)).mappings()]

    async def rebuild_source_facets(
        self, *, source_filter: str | None = None, batch_size: int = 500, limit: int | None = None
    ) -> dict[str, int]:
        processed, after = 0, 0
        through = await self.event_scan_high_water()
        while limit is None or processed < limit:
            size = (
                max(1, int(batch_size))
                if limit is None
                else min(max(1, int(batch_size)), limit - processed)
            )
            query = select(s.events).where(
                s.events.c.deleted_at.is_(None), s.events.c.id > after, s.events.c.id <= through
            )
            if source_filter:
                query = query.where(
                    s.events.c.source_key == identity(source_filter),
                    s.events.c.source == source_filter,
                )
            async with self._transaction(write=True) as connection:
                rows = (
                    (await connection.execute(query.order_by(s.events.c.id).limit(size)))
                    .mappings()
                    .all()
                )
                if not rows:
                    break
                for row in rows:
                    event = record(row).event
                    await connection.execute(
                        delete(s.facets).where(s.facets.c.event_key == identity(event.event_id))
                    )
                    values = [facet_values(facet) for facet in extract_source_facets(event)]
                    if values:
                        await connection.execute(insert(s.facets), values)
                    after = int(row["id"])
                    processed += 1
        return {"processed": processed, "indexed": processed}
