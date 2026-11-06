"""SQLite aggregate reads that never materialize full event bodies or metadata."""
from __future__ import annotations

import aiosqlite

from ...evidence import L1RetrievalScope
from ..overview_contracts import EventOverview, EventOverviewCount, EventOverviewPreview, EventOverviewQuery
from .connection import event_connection


async def read_event_overview(db_path: str, query: EventOverviewQuery) -> EventOverview:
    if not query.retrieval_scopes:
        return EventOverview()
    bucket = "CASE " + " ".join(
        f"WHEN timestamp < ? THEN {index}" for index in range(len(query.boundaries) - 1)
    ) + " END"
    scopes = [int(L1RetrievalScope.from_value(value)) for value in query.retrieval_scopes]
    where = (
        "deleted_at IS NULL AND timestamp >= ? AND timestamp < ? "
        f"AND l1_retrieval_scope IN ({','.join('?' for _ in scopes)})"
    )
    args = [*query.boundaries[1:], query.boundaries[0], query.boundaries[-1], *scopes]
    for group in query.term_groups:
        if group:
            where += " AND (" + " OR ".join("LOWER(content || ' ' || source) LIKE ? ESCAPE '\\'" for _ in group) + ")"
            args.extend('%' + term.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%' for term in group)
    scoped = f"SELECT event_id, timestamp, source, importance_score, {bucket} AS bucket FROM fact_events WHERE {where}"
    async with event_connection(db_path, profile="hot_write") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"WITH scoped AS ({scoped}) SELECT bucket, source, COUNT(*) AS count FROM scoped GROUP BY bucket, source",
            args,
        ) as cursor:
            counts = [EventOverviewCount(**dict(row)) for row in await cursor.fetchall()]
        # Rank narrow identities first; JSON extraction only touches bounded winners.
        sql = f"""WITH scoped AS ({scoped}), ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY bucket ORDER BY importance_score DESC, timestamp DESC, event_id
            ) AS rank FROM scoped
        ) SELECT r.bucket, r.event_id, r.timestamp, r.source,
            SUBSTR(COALESCE(json_extract(e.metadata_json, '$.activity_snapshot.title'), ''), 1, 160) AS title,
            SUBSTR(COALESCE(json_extract(e.metadata_json, '$.activity_snapshot.summary'), e.content, ''), 1, 400) AS summary
        FROM ranked r JOIN fact_events e ON e.event_id = r.event_id
        WHERE r.rank <= ? ORDER BY r.bucket, r.rank"""
        async with db.execute(sql, [*args, query.previews_per_bucket]) as cursor:
            previews = [EventOverviewPreview(**dict(row)) for row in await cursor.fetchall()]
    return EventOverview(counts=counts, previews=previews)
