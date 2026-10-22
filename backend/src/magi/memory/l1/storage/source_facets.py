"""SQLite source-facet indexing and filtered event reads."""

from __future__ import annotations
from typing import Any
import time
import aiosqlite
from ....core.sqlite import sqlite_connection_async
from ...event_contracts import MemoryEvent
from ..source_facets import SourceFacet, extract_source_facets
from ..ports import MemoryEventRecord
from .event_queries import select_event_columns
from .event_mapping import event_record_from_mapping

FACT_EVENTS_TABLE = "fact_events"
L1_SOURCE_FACETS_TABLE = "l1_source_facets"


def source_facet_values(facet: SourceFacet) -> tuple[Any, ...]:
    return (
        facet.event_id, facet.source, facet.facet_name, facet.text_value,
        facet.normalized_text_value, facet.numeric_value, facet.timestamp_value,
        facet.json_value, facet.created_at or time.time(),
    )


class SqliteSourceFacets:
    _db_path: str

    async def _replace_source_facets_for_event(
        self,
        db: aiosqlite.Connection,
        event: MemoryEvent,
    ) -> None:
        facets = extract_source_facets(event)
        await db.execute(
            f"DELETE FROM {L1_SOURCE_FACETS_TABLE} WHERE event_id = ?",
            (event.event_id,),
        )
        if not facets:
            return
        await db.executemany(
            f"""
            INSERT INTO {L1_SOURCE_FACETS_TABLE}(
                event_id, source, facet_name, text_value, normalized_text_value,
                numeric_value, timestamp_value, json_value, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [source_facet_values(facet) for facet in facets],
        )


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
        where_parts: list[str] = []
        args: list[Any] = []
        if event_id:
            where_parts.append("event_id = ?")
            args.append(event_id)
        if source:
            where_parts.append("source = ?")
            args.append(source)
        if sources:
            where_parts.append(f"source IN ({', '.join('?' for _ in sources)})")
            args.extend(sources)
        if facet_names:
            where_parts.append(f"facet_name IN ({', '.join('?' for _ in facet_names)})")
            args.extend(facet_names)
        if normalized_text_values:
            where_parts.append(
                f"normalized_text_value IN ({', '.join('?' for _ in normalized_text_values)})"
            )
            args.extend(normalized_text_values)
        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT event_id, source, facet_name, text_value, normalized_text_value,
                       numeric_value, timestamp_value, json_value, created_at
                FROM {L1_SOURCE_FACETS_TABLE}
                {where_sql}
                ORDER BY event_id ASC, facet_name ASC, text_value ASC
                LIMIT ?
                """,
                (*args, max(1, int(limit))),
            ) as cursor:
                rows = await cursor.fetchall()
        return [SourceFacet(
            event_id=str(row["event_id"]), source=str(row["source"]),
            facet_name=str(row["facet_name"]), text_value=row["text_value"],
            normalized_text_value=row["normalized_text_value"],
            numeric_value=float(row["numeric_value"]) if row["numeric_value"] is not None else None,
            timestamp_value=float(row["timestamp_value"]) if row["timestamp_value"] is not None else None,
            json_value=row["json_value"], created_at=float(row["created_at"]),
        ) for row in rows]


    async def count_source_facets(
        self,
        *,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str] | None = None,
    ) -> int:
        where_parts: list[str] = []
        args: list[Any] = []
        if source:
            where_parts.append("source = ?")
            args.append(source)
        if sources:
            where_parts.append(f"source IN ({', '.join('?' for _ in sources)})")
            args.extend(sources)
        if facet_names:
            where_parts.append(f"facet_name IN ({', '.join('?' for _ in facet_names)})")
            args.extend(facet_names)
        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            async with db.execute(
                f"SELECT COUNT(*) FROM {L1_SOURCE_FACETS_TABLE} {where_sql}",
                tuple(args),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0


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
        normalized_values = [value for value in normalized_text_values if value]
        if not normalized_values or not facet_names:
            return []

        source_values = list(sources or [])
        if source:
            source_values.append(source)
        source_values = list(dict.fromkeys(value for value in source_values if value))
        if not source_values:
            return []

        args: list[Any] = []
        sql = f"""
            SELECT DISTINCT {select_event_columns()}
            FROM {FACT_EVENTS_TABLE}
            LEFT JOIN l1_event_embedding_state USING(event_id)
            INNER JOIN {L1_SOURCE_FACETS_TABLE} sf USING(event_id)
            WHERE fact_events.deleted_at IS NULL
        """
        sql += f" AND sf.source IN ({', '.join('?' for _ in source_values)})"
        args.extend(source_values)
        sql += f" AND sf.facet_name IN ({', '.join('?' for _ in facet_names)})"
        args.extend(facet_names)
        sql += f" AND sf.normalized_text_value IN ({', '.join('?' for _ in normalized_values)})"
        args.extend(normalized_values)
        if user_id:
            sql += " AND fact_events.user_id = ?"
            args.append(user_id)
        if time_start is not None:
            sql += " AND fact_events.timestamp >= ?"
            args.append(float(time_start))
        if time_end is not None:
            sql += " AND fact_events.timestamp <= ?"
            args.append(float(time_end))
        sql += " ORDER BY fact_events.timestamp ASC, fact_events.id ASC LIMIT ?"
        args.append(max(1, int(limit)))

        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [event_record_from_mapping(dict(row)) for row in rows]

    async def rebuild_source_facets(
        self,
        *,
        source_filter: str | None = None,
        batch_size: int = 500,
        limit: int | None = None,
    ) -> dict[str, int]:
        processed = 0
        indexed = 0
        last_seen_id = 0
        effective_batch_size = max(1, int(batch_size))

        while True:
            args: list[Any] = [last_seen_id]
            where = "deleted_at IS NULL AND id > ?"
            if source_filter:
                where += " AND source = ?"
                args.append(source_filter)
            remaining = None if limit is None else max(0, int(limit) - processed)
            if remaining == 0:
                break
            page_size = (
                min(effective_batch_size, remaining)
                if remaining is not None
                else effective_batch_size
            )
            async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
                await db.execute("BEGIN IMMEDIATE")
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    f"""
                    SELECT {select_event_columns()}
                    FROM {FACT_EVENTS_TABLE}
                    LEFT JOIN l1_event_embedding_state USING(event_id)
                    WHERE {where}
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (*args, page_size),
                ) as cursor:
                    rows = await cursor.fetchall()
                if not rows:
                    break
                for row in rows:
                    last_seen_id = max(last_seen_id, int(row["id"]))
                    event = event_record_from_mapping(dict(row)).event
                    await self._replace_source_facets_for_event(db, event)
                    indexed += 1
                    processed += 1
                await db.commit()

        return {"processed": processed, "indexed": indexed}
