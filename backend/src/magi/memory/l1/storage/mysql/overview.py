"""MySQL aggregate overview reads with bounded text projection."""
from __future__ import annotations

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from ....evidence import L1RetrievalScope
from ...overview_contracts import EventOverview, EventOverviewCount, EventOverviewPreview, EventOverviewQuery
from .schema import events as e


async def read_event_overview(connection: AsyncConnection, query: EventOverviewQuery) -> EventOverview:
    if not query.retrieval_scopes:
        return EventOverview()
    bucket = case(*[(e.c.timestamp < end, index) for index, end in enumerate(query.boundaries[1:])])
    conditions = [
        e.c.deleted_at.is_(None), e.c.timestamp >= query.boundaries[0], e.c.timestamp < query.boundaries[-1],
        e.c.l1_retrieval_scope.in_([int(L1RetrievalScope.from_value(v)) for v in query.retrieval_scopes]),
    ]
    for group in query.term_groups:
        if group:
            conditions.append(or_(*[
                func.lower(func.concat(e.c.content, ' ', e.c.source)).contains(term.lower(), autoescape=True)
                for term in group
            ]))
    scoped = select(e.c.event_id, e.c.event_key, e.c.timestamp, e.c.source, e.c.importance_score, bucket.label('bucket')).where(*conditions).cte('scoped')
    counts = [EventOverviewCount(**dict(row)) for row in (await connection.execute(
        select(scoped.c.bucket, scoped.c.source, func.count().label('count')).group_by(scoped.c.bucket, scoped.c.source)
    )).mappings()]
    ranked = select(scoped, func.row_number().over(
        partition_by=scoped.c.bucket,
        order_by=(scoped.c.importance_score.desc(), scoped.c.timestamp.desc(), scoped.c.event_id),
    ).label('rank')).cte('ranked')
    title = func.json_unquote(func.json_extract(e.c.metadata_json, '$.activity_snapshot.title'))
    summary = func.json_unquote(func.json_extract(e.c.metadata_json, '$.activity_snapshot.summary'))
    rows = (await connection.execute(select(
        ranked.c.bucket, ranked.c.event_id, ranked.c.timestamp, ranked.c.source,
        func.substr(func.coalesce(title, ''), 1, 160).label('title'),
        func.substr(func.coalesce(summary, e.c.content, ''), 1, 400).label('summary'),
    ).select_from(ranked.join(e, (ranked.c.event_key == e.c.event_key) & (ranked.c.event_id == e.c.event_id)))
      .where(ranked.c.rank <= query.previews_per_bucket).order_by(ranked.c.bucket, ranked.c.rank))).mappings()
    return EventOverview(counts=counts, previews=[EventOverviewPreview(**dict(row)) for row in rows])
