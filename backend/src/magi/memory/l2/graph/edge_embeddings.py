"""Edge embedding helpers for the L2 cognition store."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async

logger = get_logger(__name__)
_MAX_SQL_IN_PARAMS = 900


class _EdgeEmbeddingHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    def _relation_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...


class L2StoreEdgeEmbeddingMixin:
    """Manage edge embedding readiness and vector-backed edge lookups."""

    async def get_pending_edge_embeddings(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        """Return active edges whose embedding_status is 'pending'."""
        host = cast(_EdgeEmbeddingHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM knowledge_graph WHERE embedding_status = 'pending' AND status = 'active' "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [host._relation_row_to_dict(row) for row in rows]

    async def update_edge_embedding_status(
        self,
        *,
        triple_ids: List[str],
        status: str = "ready",
    ) -> int:
        """Mark edges as embedded or failed."""
        if not triple_ids:
            return 0
        host = cast(_EdgeEmbeddingHostProtocol, self)
        await host.initialize()
        placeholders = ", ".join("?" for _ in triple_ids)
        async with sqlite_connection_async(host.db_path) as db:
            cursor = await db.execute(
                f"UPDATE knowledge_graph SET embedding_status = ? WHERE triple_id IN ({placeholders})",
                (status, *triple_ids),
            )
            await db.commit()
            return int(cursor.rowcount)

    async def search_edges_by_embedding(
        self,
        *,
        vector_index: Any,
        embedding: Any,
        limit: int = 20,
        status_filters: Optional[List[str]] = None,
        predicates: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Find graph edges similar to *embedding* via the edge vector index."""
        if vector_index is None or embedding is None:
            return []
        host = cast(_EdgeEmbeddingHostProtocol, self)
        await host.initialize()
        try:
            hits = await self._search_edge_vectors(vector_index, embedding, limit)
        except Exception as exc:
            logger.debug("Edge vector search failed: %s", exc)
            return []
        if not hits:
            return []

        triple_ids, status_filters, predicates = self._bounded_edge_search_inputs(
            triple_ids=[hit.entity_id for hit in hits],
            status_filters=status_filters,
            predicates=predicates,
        )
        distance_by_id = {hit.entity_id: hit.distance for hit in hits}
        query, args = self._build_edge_search_query(
            triple_ids=triple_ids,
            status_filters=status_filters,
            predicates=predicates,
        )
        rows = await self._fetch_edge_search_rows(host, query, args)
        return self._rank_edge_search_rows(host, rows, distance_by_id, limit)

    async def _search_edge_vectors(
        self, vector_index: Any, embedding: Any, limit: int
    ) -> list[Any]:
        return cast(list[Any], await vector_index.search(embedding=embedding, limit=limit * 3))

    def _bounded_edge_search_inputs(
        self,
        *,
        triple_ids: List[str],
        status_filters: Optional[List[str]],
        predicates: Optional[List[str]],
    ) -> tuple[List[str], Optional[List[str]], Optional[List[str]]]:
        if len(triple_ids) > _MAX_SQL_IN_PARAMS:
            logger.warning(
                "edge_embeddings: truncating %d triple_ids to %d (SQLite IN limit)",
                len(triple_ids),
                _MAX_SQL_IN_PARAMS,
            )
            triple_ids = triple_ids[:_MAX_SQL_IN_PARAMS]
        if status_filters and len(status_filters) > _MAX_SQL_IN_PARAMS:
            logger.warning(
                "edge_embeddings: truncating %d status_filters to %d",
                len(status_filters),
                _MAX_SQL_IN_PARAMS,
            )
            status_filters = list(status_filters)[:_MAX_SQL_IN_PARAMS]
        if predicates and len(predicates) > _MAX_SQL_IN_PARAMS:
            logger.warning(
                "edge_embeddings: truncating %d predicates to %d",
                len(predicates),
                _MAX_SQL_IN_PARAMS,
            )
            predicates = list(predicates)[:_MAX_SQL_IN_PARAMS]
        return triple_ids, status_filters, predicates

    def _build_edge_search_query(
        self,
        *,
        triple_ids: List[str],
        status_filters: Optional[List[str]],
        predicates: Optional[List[str]],
    ) -> tuple[str, list[Any]]:
        placeholders = ", ".join("?" for _ in triple_ids)
        args: list[Any] = list(triple_ids)

        if status_filters:
            status_filter_placeholders = ", ".join("?" for _ in status_filters)
            status_clause = f" AND status IN ({status_filter_placeholders})"
            args.extend(str(status_value).strip() for status_value in status_filters)
        else:
            status_clause = " AND status = 'active'"

        if predicates:
            predicate_placeholders = ", ".join("?" for _ in predicates)
            predicate_clause = f" AND predicate IN ({predicate_placeholders})"
            args.extend(str(predicate).strip().upper() for predicate in predicates)
        else:
            predicate_clause = ""

        query = (
            f"SELECT * FROM knowledge_graph WHERE triple_id IN ({placeholders})"
            f"{status_clause}{predicate_clause}"
        )
        return query, args

    async def _fetch_edge_search_rows(
        self,
        host: _EdgeEmbeddingHostProtocol,
        query: str,
        args: list[Any],
    ) -> list[aiosqlite.Row]:
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                return cast(list[aiosqlite.Row], await cursor.fetchall())

    def _rank_edge_search_rows(
        self,
        host: _EdgeEmbeddingHostProtocol,
        rows: list[aiosqlite.Row],
        distance_by_id: dict[str, Any],
        limit: int,
    ) -> List[Dict[str, Any]]:
        edges = [host._relation_row_to_dict(row) for row in rows]
        for edge in edges:
            edge["vector_distance"] = distance_by_id.get(edge["triple_id"])
        edges.sort(key=lambda edge: edge.get("vector_distance") or float("inf"))
        return edges[:limit]
