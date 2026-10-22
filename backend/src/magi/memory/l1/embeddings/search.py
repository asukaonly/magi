"""Vector search and ranked event retrieval helpers for L1 embeddings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, cast

from ...embedding.ports import VectorSearchHit
from ..embedding_contracts import EventChunkRecord
from ..ports import MemoryEventRecord
from .common import (
    EMBEDDING_TEXT_BUILDER_VERSION,
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

        records = await host.event_repository.fetch_events(
            ranked_chunks.event_id_order, session_id=session_id, user_id=user_id,
            event_types=[event_type] if event_type else None, source_filters=source_filters,
            domain_filters=domain_filters, l1_retrieval_scopes=l1_retrieval_scopes,
        )
        return _rank_event_records(host, records, ranked_chunks, limit=limit)

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


def _add_ranked_hit_chunk(
    ranked: _RankedEventChunks,
    *,
    hit: VectorSearchHit,
    row: EventChunkRecord | None,
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


def _rank_event_records(
    host: L1EventEmbeddingHostProtocol,
    records: list[MemoryEventRecord],
    ranked_chunks: _RankedEventChunks,
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    events_by_id = {record.event.event_id: host._record_to_dict(record) for record in records}
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
