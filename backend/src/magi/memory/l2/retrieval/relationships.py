"""Knowledge-graph relationship retrieval helpers for the L2 cognition store."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .common import L2RetrievalQueryHostProtocol


class L2StoreRelationshipQueryMixin:
    """Read and batch-query L2 knowledge-graph relationships."""

    async def count_relationships(self) -> int:
        """Count all active relationships in the knowledge graph."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'") as cursor:
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
    ) -> List[Dict[str, Any]]:
        """Query the knowledge graph."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        if status_filters:
            placeholders = ", ".join("?" for _ in status_filters)
            query = f"SELECT * FROM knowledge_graph WHERE status IN ({placeholders})"
            args: list[Any] = [str(item).strip() for item in status_filters]
        else:
            query = "SELECT * FROM knowledge_graph WHERE status = ?"
            args = [status]
        if subject_id:
            query += " AND subject_id = ?"
            args.append(subject_id)
        if object_id:
            query += " AND object_id = ?"
            args.append(object_id)
        if predicates:
            placeholders = ", ".join("?" for _ in predicates)
            query += f" AND predicate IN ({placeholders})"
            args.extend([str(item).strip().upper() for item in predicates])
        if object_types:
            placeholders = ", ".join("?" for _ in object_types)
            query += f" AND object_type IN ({placeholders})"
            args.extend([str(item).strip().lower() for item in object_types])
        if temporal_clause:
            tc_sql, tc_params = temporal_clause
            if tc_sql:
                query += f" AND {tc_sql}"
                args.extend(tc_params)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
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
        id_placeholders = ", ".join("?" for _ in unique_ids)

        if status_filters:
            status_ph = ", ".join("?" for _ in status_filters)
            status_clause = f"status IN ({status_ph})"
            status_args = [str(s).strip() for s in status_filters]
        else:
            status_clause = "status = ?"
            status_args = [status]

        direction_clause: str
        if direction == "incoming":
            direction_clause = f"object_id IN ({id_placeholders})"
        elif direction == "both":
            direction_clause = f"(subject_id IN ({id_placeholders}) OR object_id IN ({id_placeholders}))"
            unique_ids = unique_ids + unique_ids
        else:
            direction_clause = f"subject_id IN ({id_placeholders})"

        args: list[Any] = status_args + unique_ids
        query = f"SELECT * FROM knowledge_graph WHERE {status_clause} AND {direction_clause}"
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
        query += " ORDER BY updated_at DESC"

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        result: Dict[str, List[Dict[str, Any]]] = {eid: [] for eid in dict.fromkeys(entity_ids)}
        for row in rows:
            edge = host._relation_row_to_dict(row)
            subject_id = edge["subject_id"]
            object_id = edge["object_id"]
            if direction == "incoming":
                if object_id in result and len(result[object_id]) < limit_per_entity:
                    result[object_id].append(edge)
            elif direction == "both":
                if subject_id in result and len(result[subject_id]) < limit_per_entity:
                    result[subject_id].append(edge)
                if object_id in result and object_id != subject_id and len(result[object_id]) < limit_per_entity:
                    result[object_id].append(edge)
            else:
                if subject_id in result and len(result[subject_id]) < limit_per_entity:
                    result[subject_id].append(edge)
        return result
