"""SQLite event maintenance with conditional writes and durable clear fences."""

from __future__ import annotations

import time

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...evidence import EvidenceStatus
from ..maintenance_contracts import EvidenceAnnotationUpdate, EvidenceBackfillQuery, EventClearState, EventScanItem
from .event_mapping import event_record_from_mapping


def _evidence_filter(query: EvidenceBackfillQuery, through: int) -> tuple[str, list[object]]:
    clauses = ["deleted_at IS NULL", "id <= ?"]
    args: list[object] = [through]
    if query.stale_rule_version is not None:
        clauses.append("(evidence_status != ? OR evidence_rule_version != ?)")
        args.extend([int(EvidenceStatus.CLASSIFIED), query.stale_rule_version])
    for column, value in (("user_id", query.user_id), ("event_type", query.event_type)):
        if value:
            clauses.append(f"{column} = ?")
            args.append(value)
    if query.source_filters:
        clauses.append("source IN (" + ",".join("?" for _ in query.source_filters) + ")")
        args.extend(query.source_filters)
    if query.start_time is not None:
        clauses.append("timestamp >= ?")
        args.append(query.start_time)
    if query.end_time is not None:
        clauses.append("timestamp <= ?")
        args.append(query.end_time)
    return " AND ".join(clauses), args


class SqliteEventMaintenance:
    _db_path: str
    _entity_link_clear_generation: int | None

    async def initialize(self) -> None:
        """Verify the migration-owned schema without creating or repairing it."""
        async with sqlite_connection_async(self._db_path, profile="readonly") as db:
            await db.execute(
                "SELECT event_id, evidence_rule_version, l1_retrieval_scope FROM fact_events LIMIT 0"
            )
            await db.execute("SELECT event_id, available_at FROM l1_cognition_handoffs LIMIT 0")
            await self._read_clear_state(db)

    async def count_evidence_backfill(self, query: EvidenceBackfillQuery, *, through: int) -> int:
        where, args = _evidence_filter(query, through)
        async with sqlite_connection_async(self._db_path, profile="readonly") as db:
            async with db.execute(f"SELECT COUNT(*) FROM fact_events WHERE {where}", tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0])

    async def scan_evidence_backfill(
        self, query: EvidenceBackfillQuery, *, after: int, through: int, limit: int,
    ) -> list[EventScanItem]:
        where, args = _evidence_filter(query, through)
        results: list[EventScanItem] = []
        async with sqlite_connection_async(self._db_path, profile="readonly") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM fact_events WHERE {where} AND id > ? ORDER BY id LIMIT ?",
                (*args, after, limit),
            ) as cursor:
                for row in await cursor.fetchall():
                    try:
                        record = event_record_from_mapping(dict(row))
                    except (ValueError, TypeError, KeyError) as exc:
                        results.append(EventScanItem(int(row["id"]), str(row["event_id"]), None, str(exc)))
                    else:
                        results.append(EventScanItem(int(row["id"]), str(row["event_id"]), record))
        return results

    async def apply_evidence_annotations(self, updates: list[EvidenceAnnotationUpdate]) -> int:
        if not updates:
            return 0
        updated = 0
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            for update in updates:
                async with db.execute(
                    "SELECT * FROM fact_events WHERE event_id = ? AND deleted_at IS NULL",
                    (update.expected.event.event_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None or event_record_from_mapping(dict(row)) != update.expected:
                    continue
                evidence = update.evidence
                await db.execute(
                    "UPDATE fact_events SET evidence_status=?, evidence_class=?, "
                    "evidence_rule_version=?, l1_retrieval_scope=? WHERE event_id=?",
                    (int(evidence.status), int(evidence.classification), evidence.rule_version,
                     int(evidence.retrieval_scope), update.expected.event.event_id),
                )
                updated += 1
            await db.commit()
        return updated

    @staticmethod
    async def _read_clear_state(db: aiosqlite.Connection) -> EventClearState:
        async with db.execute(
            "SELECT clear_generation FROM l1_entity_link_projection_generation WHERE singleton_id = 1"
        ) as cursor:
            generation = await cursor.fetchone()
        if generation is None:
            raise RuntimeError("L1 entity-link projection generation is missing")
        async with db.execute("SELECT 1 FROM l1_event_entity_projection_state LIMIT 1") as cursor:
            has_projected = await cursor.fetchone() is not None
        return EventClearState(int(generation[0]), has_projected)

    async def get_clear_state(self) -> EventClearState:
        async with sqlite_connection_async(self._db_path, profile="readonly") as db:
            await db.execute("BEGIN")
            return await self._read_clear_state(db)

    async def clear_events(self, *, entity_link_clear_generation: int | None = None) -> int:
        """Delete source data and advance its projection fence in one transaction."""
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            state = await self._read_clear_state(db)
            generation = state.entity_link_generation
            if entity_link_clear_generation is None:
                if state.has_projected_links:
                    raise RuntimeError("L1 clear with entity-link projections requires unified memory clear")
            else:
                if entity_link_clear_generation <= generation:
                    raise RuntimeError("L1 clear must advance entity-link generation")
                generation = entity_link_clear_generation
            async with db.execute("SELECT COUNT(*) FROM fact_events WHERE deleted_at IS NULL") as cursor:
                row = await cursor.fetchone()
            count = int(row[0])
            for table in (
                "l1_cognition_handoffs", "l1_event_payload", "l1_source_facets", "l1_events_fts",
                "l1_event_chunks", "l1_event_embedding_state", "embedding_profiles",
                "l1_projected_event_entities", "l1_event_entity_projection_state", "l1_event_entities",
                "l1_session_sequences", "chat_sessions", "fact_events",
            ):
                await db.execute(f"DELETE FROM {table}")
            await db.execute(
                "UPDATE l1_entity_link_projection_generation SET clear_generation=?, updated_at=? WHERE singleton_id=1",
                (generation, time.time()),
            )
            await db.commit()
        self._entity_link_clear_generation = generation
        return count
