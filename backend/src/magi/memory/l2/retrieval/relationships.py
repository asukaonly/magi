"""Knowledge-graph relationship retrieval helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..corrections.fingerprints import scope_matches, scope_specificity
from ...sql_search import build_like_search_clause
from .common import (
    L2RetrievalQueryHostProtocol,
    bounded_scoped_candidate_limit,
    matching_scope_keys,
    select_governed_range_rows,
)
from .relationship_history import _list_governed_relationship_history
from .relationship_history import _batch_list_governed_relationship_history

_FORGOTTEN_RELATIONSHIP_EXCLUSION_SQL = (
    " AND COALESCE(authority_ref, '') NOT LIKE 'forget:%'"
    " AND COALESCE(status_reason, '') != 'user_forget'"
)


class L2StoreRelationshipQueryMixin:
    """Read and batch-query L2 knowledge-graph relationships."""

    async def list_current_relationships(
        self,
        *,
        subject_id: str | None = None,
        entity_ids: List[str] | None = None,
        direction: str = "outgoing",
        object_id: str | None = None,
        predicates: List[str] | None = None,
        object_types: List[str] | None = None,
        evidence_classes: List[str] | None = None,
        triple_ids: List[str] | None = None,
        context_scope: Mapping[str, Any] | None = None,
        effective_at: float | None = None,
        effective_range: tuple[float | None, float | None] | None = None,
        include_history: bool | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return governed relationships that are valid at one point in time.

        This is the product-facing relationship read boundary. A deprecated
        relationship remains eligible only through an explicit future
        ``valid_to`` so a scheduled situation change does not create a gap.
        Rejected, conflicted, archived, and legacy deprecated rows never pass.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        requested_scope = dict(context_scope or {})
        history_requested = (
            effective_at is not None or effective_range is not None
            if include_history is None
            else include_history
        )
        at = float(effective_at if effective_at is not None else time.time())
        if history_requested:
            return await _list_governed_relationship_history(
                host,
                subject_id=subject_id,
                entity_ids=entity_ids,
                direction=direction,
                object_id=object_id,
                predicates=predicates,
                object_types=object_types,
                evidence_classes=evidence_classes,
                triple_ids=triple_ids,
                requested_scope=requested_scope,
                effective_at=at,
                effective_range=effective_range,
                limit=limit,
            )
        sql = "SELECT * FROM knowledge_graph WHERE status IN ('active', 'deprecated')"
        args: list[Any] = []
        if subject_id:
            sql += " AND subject_id = ?"
            args.append(subject_id)
        if entity_ids:
            unique_entity_ids = list(dict.fromkeys(str(item) for item in entity_ids if item))
            if not unique_entity_ids:
                return []
            placeholders = ", ".join("?" for _ in unique_entity_ids)
            if direction == "incoming":
                sql += f" AND object_id IN ({placeholders})"
                args.extend(unique_entity_ids)
            elif direction == "both":
                sql += f" AND (subject_id IN ({placeholders})" f" OR object_id IN ({placeholders}))"
                args.extend(unique_entity_ids)
                args.extend(unique_entity_ids)
            else:
                sql += f" AND subject_id IN ({placeholders})"
                args.extend(unique_entity_ids)
        if object_id:
            sql += " AND object_id = ?"
            args.append(object_id)
        if predicates:
            placeholders = ", ".join("?" for _ in predicates)
            sql += f" AND predicate IN ({placeholders})"
            args.extend(str(item).strip().upper() for item in predicates)
        if object_types:
            placeholders = ", ".join("?" for _ in object_types)
            sql += f" AND object_type IN ({placeholders})"
            args.extend(str(item).strip().lower() for item in object_types)
        if evidence_classes:
            placeholders = ", ".join("?" for _ in evidence_classes)
            sql += f" AND evidence_class IN ({placeholders})"
            args.extend(str(item).strip() for item in evidence_classes)
        if triple_ids:
            unique_triple_ids = list(dict.fromkeys(str(item) for item in triple_ids if item))
            if not unique_triple_ids:
                return []
            placeholders = ", ".join("?" for _ in unique_triple_ids)
            sql += f" AND triple_id IN ({placeholders})"
            args.extend(unique_triple_ids)
        sql += " AND (status != 'deprecated' OR valid_to IS NOT NULL)"
        if effective_range is None:
            sql += " AND (valid_from IS NULL OR valid_from <= ?)"
            sql += " AND (valid_to IS NULL OR valid_to > ?)"
            args.extend((at, at))
            sql += " AND (expires_at IS NULL OR expires_at > ?)"
            args.append(at)
        else:
            range_start, range_end = effective_range
            if range_end is not None:
                sql += " AND (valid_from IS NULL OR valid_from <= ?)"
                args.append(float(range_end))
            if range_start is not None:
                sql += " AND (valid_to IS NULL OR valid_to > ?)"
                args.append(float(range_start))
                sql += " AND (expires_at IS NULL OR expires_at > ?)"
                args.append(float(range_start))
        if not requested_scope:
            sql += " AND scope_key = 'global'"
            sql += " ORDER BY updated_at DESC"
            sql += " LIMIT ?"
            args.append(max(1, int(limit)) * 4)
        else:
            eligible_scope_keys = matching_scope_keys(requested_scope)
            placeholders = ", ".join("?" for _ in eligible_scope_keys)
            sql += f" AND scope_key IN ({placeholders})"
            args.extend(eligible_scope_keys)
            sql += (
                " ORDER BY json_array_length(scope_json, '$.all_of') DESC,"
                " updated_at DESC LIMIT ?"
            )
            args.append(bounded_scoped_candidate_limit(limit))
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        relationships = [host._relation_row_to_dict(row) for row in rows]
        relationships = [
            relationship
            for relationship in relationships
            if scope_matches(relationship.get("scope"), requested_scope)
        ]
        relationships.sort(
            key=lambda relationship: (
                scope_specificity(relationship.get("scope")),
                float(relationship.get("updated_at") or 0.0),
            ),
            reverse=True,
        )

        if effective_range is not None:
            return select_governed_range_rows(
                relationships,
                identity_field="triple_id",
                range_start=effective_range[0],
                range_end=effective_range[1],
                limit=limit,
            )

        current_by_slot: dict[str, Dict[str, Any]] = {}
        for relationship in relationships:
            current_by_slot.setdefault(
                relationship["slot_key"] or relationship["triple_id"],
                relationship,
            )
            if len(current_by_slot) >= limit:
                break
        return list(current_by_slot.values())

    async def batch_list_current_relationships(
        self,
        *,
        entity_ids: List[str],
        direction: str = "outgoing",
        object_id: str | None = None,
        predicates: List[str] | None = None,
        object_types: List[str] | None = None,
        evidence_classes: List[str] | None = None,
        context_scope: Mapping[str, Any] | None = None,
        effective_at: float | None = None,
        effective_range: tuple[float | None, float | None] | None = None,
        include_history: bool | None = None,
        limit_per_entity: int = 100,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return governed relationships for many entities with fixed query count."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        unique_ids = list(dict.fromkeys(str(item) for item in entity_ids if item))
        if not unique_ids:
            return {}
        requested_scope = dict(context_scope or {})
        history_requested = (
            effective_at is not None or effective_range is not None
            if include_history is None
            else include_history
        )
        at = float(effective_at if effective_at is not None else time.time())
        if history_requested:
            return await _batch_list_governed_relationship_history(
                host,
                entity_ids=unique_ids,
                direction=direction,
                object_id=object_id,
                predicates=predicates,
                object_types=object_types,
                evidence_classes=evidence_classes,
                requested_scope=requested_scope,
                effective_at=at,
                effective_range=effective_range,
                limit_per_entity=limit_per_entity,
            )

        requested_limit = max(1, int(limit_per_entity))
        join_clause = self._governed_batch_entity_join_clause(direction=direction)
        query = f"""
            SELECT requested.entity_id AS governed_bucket_entity_id,
                   relationships.*
            FROM requested_entities AS requested
            JOIN knowledge_graph AS relationships ON {join_clause}
            WHERE relationships.status IN ('active', 'deprecated')
        """
        args: list[Any] = []
        if object_id:
            query += " AND relationships.object_id = ?"
            args.append(object_id)
        if predicates:
            placeholders = ", ".join("?" for _ in predicates)
            query += f" AND relationships.predicate IN ({placeholders})"
            args.extend(str(item).strip().upper() for item in predicates)
        if object_types:
            placeholders = ", ".join("?" for _ in object_types)
            query += f" AND relationships.object_type IN ({placeholders})"
            args.extend(str(item).strip().lower() for item in object_types)
        if evidence_classes:
            placeholders = ", ".join("?" for _ in evidence_classes)
            query += f" AND relationships.evidence_class IN ({placeholders})"
            args.extend(str(item).strip() for item in evidence_classes)
        query += " AND (relationships.status != 'deprecated' OR relationships.valid_to IS NOT NULL)"
        if effective_range is None:
            query += " AND (relationships.valid_from IS NULL OR relationships.valid_from <= ?)"
            query += " AND (relationships.valid_to IS NULL OR relationships.valid_to > ?)"
            query += " AND (relationships.expires_at IS NULL OR relationships.expires_at > ?)"
            args.extend((at, at, at))
        else:
            range_start, range_end = effective_range
            if range_end is not None:
                query += " AND (relationships.valid_from IS NULL OR relationships.valid_from <= ?)"
                args.append(float(range_end))
            if range_start is not None:
                query += " AND (relationships.valid_to IS NULL OR relationships.valid_to > ?)"
                query += " AND (relationships.expires_at IS NULL OR relationships.expires_at > ?)"
                args.extend((float(range_start), float(range_start)))
        if not requested_scope:
            query += " AND relationships.scope_key = 'global'"
            ordering = "candidates.updated_at DESC"
            candidate_limit = requested_limit * 4
        else:
            eligible_scope_keys = matching_scope_keys(requested_scope)
            placeholders = ", ".join("?" for _ in eligible_scope_keys)
            query += f" AND relationships.scope_key IN ({placeholders})"
            args.extend(eligible_scope_keys)
            ordering = (
                "json_array_length(candidates.scope_json, '$.all_of') DESC, "
                "candidates.updated_at DESC"
            )
            candidate_limit = bounded_scoped_candidate_limit(requested_limit)
        ranked_query = f"""
            WITH requested_entities(entity_id) AS (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            ), candidates AS (
                {query}
            ), ranked_relationships AS (
                SELECT candidates.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY candidates.governed_bucket_entity_id
                           ORDER BY {ordering}
                       ) AS governed_entity_rank
                FROM candidates
            )
            SELECT *
            FROM ranked_relationships
            WHERE governed_entity_rank <= ?
            ORDER BY governed_bucket_entity_id, governed_entity_rank
        """
        requested_json = json.dumps(unique_ids, ensure_ascii=False, separators=(",", ":"))
        query_args = [requested_json, *args, candidate_limit]
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(ranked_query, tuple(query_args)) as cursor:
                rows = await cursor.fetchall()

        candidates_by_entity: Dict[str, List[Dict[str, Any]]] = {
            entity_id: [] for entity_id in unique_ids
        }
        for row in rows:
            candidates_by_entity[str(row["governed_bucket_entity_id"])].append(
                host._relation_row_to_dict(row)
            )
        result: Dict[str, List[Dict[str, Any]]] = {}
        for entity_id, relationships in candidates_by_entity.items():
            relationships = [
                relationship
                for relationship in relationships
                if scope_matches(relationship.get("scope"), requested_scope)
            ]
            relationships.sort(
                key=lambda relationship: (
                    scope_specificity(relationship.get("scope")),
                    float(relationship.get("updated_at") or 0.0),
                ),
                reverse=True,
            )
            if effective_range is not None:
                result[entity_id] = select_governed_range_rows(
                    relationships,
                    identity_field="triple_id",
                    range_start=effective_range[0],
                    range_end=effective_range[1],
                    limit=requested_limit,
                )
                continue
            current_by_slot: dict[str, Dict[str, Any]] = {}
            for relationship in relationships:
                current_by_slot.setdefault(
                    relationship["slot_key"] or relationship["triple_id"],
                    relationship,
                )
                if len(current_by_slot) >= requested_limit:
                    break
            result[entity_id] = list(current_by_slot.values())
        return result

    @staticmethod
    def _governed_batch_entity_join_clause(*, direction: str) -> str:
        if direction == "incoming":
            return "relationships.object_id = requested.entity_id"
        if direction == "both":
            return (
                "(relationships.subject_id = requested.entity_id "
                "OR relationships.object_id = requested.entity_id)"
            )
        return "relationships.subject_id = requested.entity_id"

    async def count_relationships(
        self,
        *,
        query: str | None = None,
        include_inactive: bool = False,
    ) -> int:
        """Count relationships, optionally including governed historical rows."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        sql = "SELECT COUNT(*) FROM knowledge_graph WHERE 1=1"
        sql += _FORGOTTEN_RELATIONSHIP_EXCLUSION_SQL
        args: list[Any] = []
        if not include_inactive:
            sql += " AND status = 'active'"
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
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Query the knowledge graph."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        search_query = query
        if include_inactive:
            sql = "SELECT * FROM knowledge_graph WHERE 1=1"
            sql += _FORGOTTEN_RELATIONSHIP_EXCLUSION_SQL
            args: list[Any] = []
        elif status_filters:
            placeholders = ", ".join("?" for _ in status_filters)
            sql = f"SELECT * FROM knowledge_graph WHERE status IN ({placeholders})"
            sql += _FORGOTTEN_RELATIONSHIP_EXCLUSION_SQL
            args: list[Any] = [str(item).strip() for item in status_filters]
        else:
            sql = "SELECT * FROM knowledge_graph WHERE status = ?"
            sql += _FORGOTTEN_RELATIONSHIP_EXCLUSION_SQL
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
            sql += f" AND evidence_class IN ({ec_ph})"
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
        query = (
            f"SELECT * FROM knowledge_graph WHERE {status_clause} AND {direction_clause}"
            + _FORGOTTEN_RELATIONSHIP_EXCLUSION_SQL
        )
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
            query += f" AND evidence_class IN ({ec_ph})"
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
