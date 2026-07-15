"""Knowledge-graph relationship retrieval helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..corrections.fingerprints import scope_key
from ...sql_search import build_like_search_clause
from .common import L2RetrievalQueryHostProtocol


class L2StoreRelationshipQueryMixin:
    """Read and batch-query L2 knowledge-graph relationships."""

    async def list_current_relationships(
        self,
        *,
        subject_id: str | None = None,
        object_id: str | None = None,
        context_scope: Mapping[str, Any] | None = None,
        effective_at: float | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return one current relationship per governed slot and context."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        requested_scope_key = scope_key(context_scope)
        at = float(effective_at if effective_at is not None else time.time())
        sql = "SELECT * FROM knowledge_graph WHERE status = 'active'"
        args: list[Any] = []
        if subject_id:
            sql += " AND subject_id = ?"
            args.append(subject_id)
        if object_id:
            sql += " AND object_id = ?"
            args.append(object_id)
        sql += " AND (valid_from IS NULL OR valid_from <= ?)"
        sql += " AND (valid_to IS NULL OR valid_to > ?)"
        args.extend((at, at))
        if requested_scope_key == "global":
            sql += " AND scope_key = 'global'"
        else:
            sql += " AND scope_key IN ('global', ?)"
            args.append(requested_scope_key)
        sql += " ORDER BY CASE WHEN scope_key = ? THEN 0 ELSE 1 END, updated_at DESC"
        args.append(requested_scope_key)
        sql += " LIMIT ?"
        args.append(max(1, int(limit)) * 2)
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        current_by_slot: dict[str, Dict[str, Any]] = {}
        for row in rows:
            relationship = host._relation_row_to_dict(row)
            current_by_slot.setdefault(
                relationship["slot_key"] or relationship["triple_id"],
                relationship,
            )
            if len(current_by_slot) >= limit:
                break
        return list(current_by_slot.values())

    async def count_relationships(self, *, query: str | None = None) -> int:
        """Count all active relationships in the knowledge graph."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        sql = "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'"
        args: list[Any] = []
        search_sql, search_args = build_like_search_clause(
            [
                "triple_id",
                "subject_id",
                "subject_type",
                "predicate",
                "object_id",
                "object_type",
                "fact_kind",
                "evidence_event_ids",
                "evidence_text",
                "natural_summary",
                "source_type",
                "extraction_method",
                "evidence_class",
                "status",
            ],
            query,
        )
        sql += search_sql
        args.extend(search_args)
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(sql, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_relationships(
        self,
        *,
        subject_id: Optional[str] = None,
        object_id: Optional[str] = None,
        status: str = "active",
        status_filters: Optional[List[str]] = None,
        predicates: Optional[List[str]] = None,
        object_types: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
        temporal_clause: Optional[tuple[str, list[Any]]] = None,
        evidence_classes: Optional[List[str]] = None,
        query: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Query the knowledge graph."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        search_query = query
        if status_filters:
            placeholders = ", ".join("?" for _ in status_filters)
            sql = f"SELECT * FROM knowledge_graph WHERE status IN ({placeholders})"
            args: list[Any] = [str(item).strip() for item in status_filters]
        else:
            sql = "SELECT * FROM knowledge_graph WHERE status = ?"
            args = [status]
        if subject_id:
            sql += " AND subject_id = ?"
            args.append(subject_id)
        if object_id:
            sql += " AND object_id = ?"
            args.append(object_id)
        if predicates:
            placeholders = ", ".join("?" for _ in predicates)
            sql += f" AND predicate IN ({placeholders})"
            args.extend([str(item).strip().upper() for item in predicates])
        if object_types:
            placeholders = ", ".join("?" for _ in object_types)
            sql += f" AND object_type IN ({placeholders})"
            args.extend([str(item).strip().lower() for item in object_types])
        if temporal_clause:
            tc_sql, tc_params = temporal_clause
            if tc_sql:
                sql += f" AND {tc_sql}"
                args.extend(tc_params)
        if evidence_classes:
            ec_ph = ", ".join("?" for _ in evidence_classes)
            # NULL passes through: pre-backfill rows must not be silently excluded.
            sql += f" AND (evidence_class IN ({ec_ph}) OR evidence_class IS NULL)"
            args.extend(str(c).strip() for c in evidence_classes)
        search_sql, search_args = build_like_search_clause(
            [
                "triple_id",
                "subject_id",
                "subject_type",
                "predicate",
                "object_id",
                "object_type",
                "fact_kind",
                "evidence_event_ids",
                "evidence_text",
                "natural_summary",
                "source_type",
                "extraction_method",
                "evidence_class",
                "status",
            ],
            search_query,
        )
        sql += search_sql
        args.extend(search_args)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._relation_row_to_dict(row) for row in rows]

    async def get_relationship(self, *, triple_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one graph edge by id."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        async with aiosqlite.connect(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return host._relation_row_to_dict(row) if row else None

    async def find_edges_by_event_id(self, event_id: str) -> List[Dict[str, Any]]:
        """Return graph edges that cite a specific event as evidence."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        escaped = str(event_id).replace('"', '""')
        pattern = f'%"{escaped}"%'
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM knowledge_graph WHERE evidence_event_ids LIKE ? AND status = 'active' ORDER BY updated_at DESC LIMIT 500",
                (pattern,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            host._relation_row_to_dict(row)
            for row in rows
            if event_id in json.loads(row["evidence_event_ids"] or "[]")
        ]

    async def batch_get_relationships(
        self,
        *,
        entity_ids: List[str],
        direction: str = "outgoing",
        status: str = "active",
        status_filters: Optional[List[str]] = None,
        predicates: Optional[List[str]] = None,
        target_object_id: Optional[str] = None,
        object_types: Optional[List[str]] = None,
        limit_per_entity: int = 100,
        temporal_clause: Optional[tuple[str, list[Any]]] = None,
        evidence_classes: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Batch-fetch relationships for multiple entities in one query."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        if not entity_ids:
            return {}

        unique_ids = list(dict.fromkeys(entity_ids))
        query, args = self._build_batch_relationship_query(
            unique_ids=unique_ids,
            direction=direction,
            status=status,
            status_filters=status_filters,
            predicates=predicates,
            target_object_id=target_object_id,
            object_types=object_types,
            temporal_clause=temporal_clause,
            evidence_classes=evidence_classes,
        )
        rows = await self._fetch_relationship_rows(host, query, args)
        return self._bucket_relationship_rows(
            host=host,
            rows=rows,
            entity_ids=entity_ids,
            direction=direction,
            limit_per_entity=limit_per_entity,
        )

    def _build_batch_relationship_query(
        self,
        *,
        unique_ids: List[str],
        direction: str,
        status: str,
        status_filters: Optional[List[str]],
        predicates: Optional[List[str]],
        target_object_id: Optional[str],
        object_types: Optional[List[str]],
        temporal_clause: Optional[tuple[str, list[Any]]],
        evidence_classes: Optional[List[str]],
    ) -> tuple[str, list[Any]]:
        status_clause, status_args = self._relationship_status_clause(
            status=status,
            status_filters=status_filters,
        )
        direction_clause, direction_args = self._relationship_direction_clause(
            direction=direction,
            unique_ids=unique_ids,
        )
        query = f"SELECT * FROM knowledge_graph WHERE {status_clause} AND {direction_clause}"
        args = status_args + direction_args
        query, args = self._append_batch_relationship_filters(
            query=query,
            args=args,
            predicates=predicates,
            target_object_id=target_object_id,
            object_types=object_types,
            temporal_clause=temporal_clause,
            evidence_classes=evidence_classes,
        )
        return f"{query} ORDER BY updated_at DESC", args

    def _relationship_status_clause(
        self,
        *,
        status: str,
        status_filters: Optional[List[str]],
    ) -> tuple[str, list[Any]]:
        if not status_filters:
            return "status = ?", [status]
        status_ph = ", ".join("?" for _ in status_filters)
        return f"status IN ({status_ph})", [str(s).strip() for s in status_filters]

    def _relationship_direction_clause(
        self,
        *,
        direction: str,
        unique_ids: List[str],
    ) -> tuple[str, list[Any]]:
        id_placeholders = ", ".join("?" for _ in unique_ids)
        if direction == "incoming":
            return f"object_id IN ({id_placeholders})", list(unique_ids)
        if direction == "both":
            return (
                f"(subject_id IN ({id_placeholders}) OR object_id IN ({id_placeholders}))",
                list(unique_ids) + list(unique_ids),
            )
        return f"subject_id IN ({id_placeholders})", list(unique_ids)

    def _append_batch_relationship_filters(
        self,
        *,
        query: str,
        args: list[Any],
        predicates: Optional[List[str]],
        target_object_id: Optional[str],
        object_types: Optional[List[str]],
        temporal_clause: Optional[tuple[str, list[Any]]],
        evidence_classes: Optional[List[str]],
    ) -> tuple[str, list[Any]]:
        if predicates:
            pred_ph = ", ".join("?" for _ in predicates)
            query += f" AND predicate IN ({pred_ph})"
            args.extend(str(p).strip().upper() for p in predicates)
        if target_object_id:
            query += " AND object_id = ?"
            args.append(str(target_object_id))
        if object_types:
            ot_ph = ", ".join("?" for _ in object_types)
            query += f" AND object_type IN ({ot_ph})"
            args.extend(str(t).strip().lower() for t in object_types)
        if temporal_clause:
            tc_sql, tc_params = temporal_clause
            if tc_sql:
                query += f" AND {tc_sql}"
                args.extend(tc_params)
        if evidence_classes:
            ec_ph = ", ".join("?" for _ in evidence_classes)
            # NULL passes through: pre-backfill rows must not be silently excluded.
            query += f" AND (evidence_class IN ({ec_ph}) OR evidence_class IS NULL)"
            args.extend(str(c).strip() for c in evidence_classes)
        return query, args

    async def _fetch_relationship_rows(
        self,
        host: L2RetrievalQueryHostProtocol,
        query: str,
        args: list[Any],
    ) -> list[aiosqlite.Row]:
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                return cast(list[aiosqlite.Row], await cursor.fetchall())

    def _bucket_relationship_rows(
        self,
        *,
        host: L2RetrievalQueryHostProtocol,
        rows: list[aiosqlite.Row],
        entity_ids: List[str],
        direction: str,
        limit_per_entity: int,
    ) -> Dict[str, List[Dict[str, Any]]]:
        result: Dict[str, List[Dict[str, Any]]] = {eid: [] for eid in dict.fromkeys(entity_ids)}
        for row in rows:
            edge = host._relation_row_to_dict(row)
            self._append_edge_to_relationship_bucket(
                result=result,
                edge=edge,
                direction=direction,
                limit_per_entity=limit_per_entity,
            )
        return result

    def _append_edge_to_relationship_bucket(
        self,
        *,
        result: Dict[str, List[Dict[str, Any]]],
        edge: Dict[str, Any],
        direction: str,
        limit_per_entity: int,
    ) -> None:
        subject_id = edge["subject_id"]
        object_id = edge["object_id"]
        if direction == "incoming":
            self._append_limited_relationship(result, object_id, edge, limit_per_entity)
            return
        if direction == "both":
            self._append_limited_relationship(result, subject_id, edge, limit_per_entity)
            if object_id != subject_id:
                self._append_limited_relationship(result, object_id, edge, limit_per_entity)
            return
        self._append_limited_relationship(result, subject_id, edge, limit_per_entity)

    def _append_limited_relationship(
        self,
        result: Dict[str, List[Dict[str, Any]]],
        entity_id: str,
        edge: Dict[str, Any],
        limit_per_entity: int,
    ) -> None:
        if entity_id in result and len(result[entity_id]) < limit_per_entity:
            result[entity_id].append(edge)
