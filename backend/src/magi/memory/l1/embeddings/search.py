"""Vector search and ranked event retrieval helpers for L1 embeddings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.sqlite_vec_index import VectorSearchHit
from ...evidence import L1RetrievalScope
from ...event_contracts import MemoryDomain
from .common import (
    EMBEDDING_TEXT_BUILDER_VERSION,
    FACT_EVENTS_TABLE,
    L1EventEmbeddingHostProtocol,
    logger,
)


@dataclass(slots=True)
class _RankedEventChunks:
    event_id_order: list[str] = field(default_factory=list)
    chunks_by_event: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    best_distance_by_event: dict[str, float] = field(default_factory=dict)


class L1EventEmbeddingSearchMixin:
    """Own semantic search over L1 event chunks and ranked event hydration."""

    async def vector_search(
        self,
        *,
        query: str,
        limit: int = 100,
        user_id: Optional[str] = None,
    ) -> list[VectorSearchHit]:
        """Semantic vector search over L1 event chunks."""
        return await self._semantic_search_event_hits(
            query=query,
            limit=limit,
            user_id=user_id,
        )

    async def _semantic_search_event_hits(
        self, *, query: str, limit: int, user_id: str | None = None
    ) -> list[VectorSearchHit]:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if (
            not host._vectors_enabled()
            or host._embedding_service is None
            or host._vector_index is None
            or not query.strip()
        ):
            return []
        embedding = await host._embedding_service.embed_text(query)
        if embedding is None:
            return []
        embedding = host._embedding_service.result_for_index(
            embedding,
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )
        try:
            return cast(
                list[VectorSearchHit],
                await host._vector_index.search(
                    embedding=embedding, limit=limit, partition_value=user_id
                ),
            )
        except Exception as exc:
            logger.warning("Failed semantic search over L1 events: %s", exc)
            return []

    async def _fetch_ranked_events(
        self,
        *,
        hits: list[VectorSearchHit],
        session_id: Optional[str],
        user_id: Optional[str],
        event_type: Optional[str],
        source_filters: Optional[List[str]],
        domain_filters: Optional[List[str]],
        limit: int,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if not hits:
            return []
        ranked_chunks = await self._ranked_event_chunks(host, hits)
        if not ranked_chunks.event_id_order:
            return []

        query_parts = _ranked_event_query(
            event_id_order=ranked_chunks.event_id_order,
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            source_filters=source_filters,
            domain_filters=domain_filters,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        if query_parts is None:
            return []
        query, args = query_parts
        rows = await self._fetch_ranked_event_rows(host, query, args)
        return _rank_event_rows(host, rows, ranked_chunks, limit=limit)

    async def _ranked_event_chunks(
        self,
        host: L1EventEmbeddingHostProtocol,
        hits: list[VectorSearchHit],
    ) -> _RankedEventChunks:
        chunk_rows = await host._fetch_chunk_rows_by_ids([hit.entity_id for hit in hits])
        chunk_by_id = {str(row["chunk_id"]): row for row in chunk_rows}
        ranked = _RankedEventChunks()
        for hit in hits:
            _add_ranked_hit_chunk(ranked, hit=hit, row=chunk_by_id.get(hit.entity_id))
        return ranked

    async def _fetch_ranked_event_rows(
        self,
        host: L1EventEmbeddingHostProtocol,
        query: str,
        args: list[Any],
    ) -> list[aiosqlite.Row]:
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                return cast(list[aiosqlite.Row], await cursor.fetchall())


def _add_ranked_hit_chunk(
    ranked: _RankedEventChunks,
    *,
    hit: VectorSearchHit,
    row: Any,
) -> None:
    if row is None:
        return
    event_id = str(row["event_id"])
    if event_id not in ranked.chunks_by_event:
        ranked.event_id_order.append(event_id)
        ranked.chunks_by_event[event_id] = []
        ranked.best_distance_by_event[event_id] = hit.distance
    ranked.best_distance_by_event[event_id] = min(
        ranked.best_distance_by_event[event_id], hit.distance
    )
    ranked.chunks_by_event[event_id].append(
        {
            "chunk_id": str(row["chunk_id"]),
            "chunk_index": int(row["chunk_index"]),
            "text": str(row["chunk_text"]),
            "char_start": int(row["char_start"]),
            "char_end": int(row["char_end"]),
            "distance": hit.distance,
        }
    )


def _ranked_event_query(
    *,
    event_id_order: list[str],
    session_id: Optional[str],
    user_id: Optional[str],
    event_type: Optional[str],
    source_filters: Optional[List[str]],
    domain_filters: Optional[List[str]],
    l1_retrieval_scopes: Optional[List[str]],
) -> tuple[str, list[Any]] | None:
    query = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
    args: list[Any] = []
    placeholders = ", ".join("?" for _ in event_id_order)
    query += f" AND event_id IN ({placeholders})"
    args.extend(event_id_order)
    query, args = _append_ranked_event_filters(
        query=query,
        args=args,
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        source_filters=source_filters,
    )
    scope_filter = _ranked_event_scope_filter(l1_retrieval_scopes)
    if scope_filter is None and l1_retrieval_scopes is not None:
        return None
    if scope_filter is not None:
        query += scope_filter[0]
        args.extend(scope_filter[1])
    query, args = _append_ranked_event_domain_filter(query, args, domain_filters)
    return query, args


def _append_ranked_event_filters(
    *,
    query: str,
    args: list[Any],
    session_id: Optional[str],
    user_id: Optional[str],
    event_type: Optional[str],
    source_filters: Optional[List[str]],
) -> tuple[str, list[Any]]:
    if session_id:
        query += " AND session_id = ?"
        args.append(session_id)
    if user_id:
        query += " AND user_id = ?"
        args.append(user_id)
    if event_type:
        query += " AND event_type = ?"
        args.append(event_type)
    if source_filters:
        source_placeholders = ", ".join("?" for _ in source_filters)
        query += f" AND source IN ({source_placeholders})"
        args.extend(source_filters)
    return query, args


def _ranked_event_scope_filter(
    l1_retrieval_scopes: Optional[List[str]],
) -> tuple[str, list[Any]] | None:
    if l1_retrieval_scopes is None:
        return "", []
    if not l1_retrieval_scopes:
        return None
    scope_placeholders = ", ".join("?" for _ in l1_retrieval_scopes)
    return (
        f" AND l1_retrieval_scope IN ({scope_placeholders})",
        [int(L1RetrievalScope.from_value(scope)) for scope in l1_retrieval_scopes],
    )


def _append_ranked_event_domain_filter(
    query: str,
    args: list[Any],
    domain_filters: Optional[List[str]],
) -> tuple[str, list[Any]]:
    allowed_domains = [MemoryDomain.from_value(value) for value in domain_filters or []]
    if allowed_domains:
        domain_placeholders = ", ".join("?" for _ in allowed_domains)
        query += f" AND memory_domain IN ({domain_placeholders})"
        args.extend(int(domain) for domain in allowed_domains)
    else:
        query += " AND memory_domain != ?"
        args.append(int(MemoryDomain.RUNTIME_TELEMETRY))
    return query, args


def _rank_event_rows(
    host: L1EventEmbeddingHostProtocol,
    rows: list[aiosqlite.Row],
    ranked_chunks: _RankedEventChunks,
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    events_by_id = {str(row["event_id"]): host._row_to_dict(row) for row in rows}
    ranked: list[Dict[str, Any]] = []
    for event_id in ranked_chunks.event_id_order:
        event = events_by_id.get(event_id)
        if event is None:
            continue
        event["distance"] = ranked_chunks.best_distance_by_event[event_id]
        event["matched_chunks"] = ranked_chunks.chunks_by_event.get(event_id, [])
        ranked.append(event)
        if len(ranked) >= limit:
            break
    return ranked
