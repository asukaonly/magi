"""Vector search and ranked event retrieval helpers for L1 embeddings."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.sqlite_vec_index import VectorSearchHit
from ...event_contracts import MemoryDomain
from .common import FACT_EVENTS_TABLE, L1EventEmbeddingHostProtocol, logger


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
    ) -> List[Dict[str, Any]]:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if not hits:
            return []
        query = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
        chunk_ids = [hit.entity_id for hit in hits]
        chunk_rows = await host._fetch_chunk_rows_by_ids(chunk_ids)
        chunk_by_id = {str(row["chunk_id"]): row for row in chunk_rows}
        event_id_order: list[str] = []
        chunks_by_event: dict[str, list[dict[str, Any]]] = {}
        best_distance_by_event: dict[str, float] = {}
        for hit in hits:
            row = chunk_by_id.get(hit.entity_id)
            if row is None:
                continue
            event_id = str(row["event_id"])
            if event_id not in chunks_by_event:
                event_id_order.append(event_id)
                chunks_by_event[event_id] = []
                best_distance_by_event[event_id] = hit.distance
            best_distance_by_event[event_id] = min(best_distance_by_event[event_id], hit.distance)
            chunks_by_event[event_id].append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "chunk_index": int(row["chunk_index"]),
                    "text": str(row["chunk_text"]),
                    "char_start": int(row["char_start"]),
                    "char_end": int(row["char_end"]),
                    "distance": hit.distance,
                }
            )
        if not event_id_order:
            return []

        args: list[Any] = []
        placeholders = ", ".join("?" for _ in event_id_order)
        query += f" AND event_id IN ({placeholders})"
        args.extend(event_id_order)
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
        allowed_domains = [MemoryDomain.from_value(value) for value in domain_filters or []]
        if allowed_domains:
            domain_placeholders = ", ".join("?" for _ in allowed_domains)
            query += f" AND memory_domain IN ({domain_placeholders})"
            args.extend(int(domain) for domain in allowed_domains)
        else:
            query += " AND memory_domain != ?"
            args.append(int(MemoryDomain.RUNTIME_TELEMETRY))

        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        events_by_id = {str(row["event_id"]): host._row_to_dict(row) for row in rows}
        ranked: list[Dict[str, Any]] = []
        for event_id in event_id_order:
            event = events_by_id.get(event_id)
            if event is None:
                continue
            event["distance"] = best_distance_by_event[event_id]
            event["matched_chunks"] = chunks_by_event.get(event_id, [])
            ranked.append(event)
            if len(ranked) >= limit:
                break
        return ranked
