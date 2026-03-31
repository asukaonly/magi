"""Shared embedding write pipeline for memory layers."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .chunking import ChunkedText
from .embedding_service import EmbeddingResult, MemoryEmbeddingService
from .sqlite_vec_index import SqliteVecIndex

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EmbeddingPipelineItem:
    """One parent object and its chunk texts ready for vector upsert."""

    parent_id: str
    chunks: list[ChunkedText]
    metadata: dict[str, Any] = field(default_factory=dict)
    payload: Any = None


@dataclass(slots=True)
class EmbeddingPipelineResult:
    """Successful vector write result for one parent object."""

    parent_id: str
    chunks: list[ChunkedText]
    embeddings: list[EmbeddingResult]
    metadata: dict[str, Any]
    payload: Any
    embedded_at: float


class MemoryEmbeddingPipeline:
    """Embed prepared chunk texts and persist them through one vector index."""

    def __init__(
        self,
        *,
        embedding_service: MemoryEmbeddingService,
        vector_index: SqliteVecIndex,
    ) -> None:
        self._embedding_service = embedding_service
        self._vector_index = vector_index

    async def upsert_items(self, items: list[EmbeddingPipelineItem]) -> list[EmbeddingPipelineResult]:
        """Embed *items* and write all chunk vectors, with single-row fallback."""
        prepared_items = [item for item in items if item.chunks]
        if not prepared_items:
            return []

        texts = [chunk.text for item in prepared_items for chunk in item.chunks]
        embeddings = await self._embed_texts(texts)
        if not embeddings:
            return []

        successful_results: list[EmbeddingPipelineResult] = []
        vector_items: list[dict[str, Any]] = []
        embedded_at = time.time()
        embedding_index = 0
        for item in prepared_items:
            chunk_embeddings = embeddings[embedding_index: embedding_index + len(item.chunks)]
            embedding_index += len(item.chunks)
            if len(chunk_embeddings) != len(item.chunks) or any(embedding is None for embedding in chunk_embeddings):
                continue
            typed_embeddings = [embedding for embedding in chunk_embeddings if embedding is not None]
            successful_results.append(
                EmbeddingPipelineResult(
                    parent_id=item.parent_id,
                    chunks=item.chunks,
                    embeddings=typed_embeddings,
                    metadata=dict(item.metadata),
                    payload=item.payload,
                    embedded_at=embedded_at,
                )
            )
            for chunk, embedding in zip(item.chunks, typed_embeddings):
                metadata = dict(item.metadata)
                metadata.setdefault("chunk_index", chunk.chunk_index)
                vector_items.append(
                    {
                        "entity_id": self._vector_entity_id(item.parent_id, chunk),
                        "embedding": embedding,
                        "metadata": metadata,
                    }
                )
        if not vector_items:
            return []

        try:
            await self._vector_index.upsert_many(vector_items)
            return successful_results
        except Exception as exc:
            logger.warning("Failed batch upsert for memory embeddings, falling back to single-row writes: %s", exc)

        persisted_results: list[EmbeddingPipelineResult] = []
        vector_items_by_parent = {
            result.parent_id: [
                {
                    "entity_id": self._vector_entity_id(result.parent_id, chunk),
                    "embedding": embedding,
                    "metadata": {**result.metadata, "chunk_index": chunk.chunk_index},
                }
                for chunk, embedding in zip(result.chunks, result.embeddings)
            ]
            for result in successful_results
        }
        for result in successful_results:
            try:
                for vector_item in vector_items_by_parent[result.parent_id]:
                    await self._vector_index.upsert(
                        entity_id=str(vector_item["entity_id"]),
                        embedding=vector_item["embedding"],
                        metadata=vector_item.get("metadata"),
                    )
                persisted_results.append(result)
            except Exception as item_exc:
                logger.warning("Failed to upsert memory embedding chunks for %s: %s", result.parent_id, item_exc)
        return persisted_results

    async def _embed_texts(self, texts: list[str]) -> list[EmbeddingResult | None]:
        if hasattr(self._embedding_service, "embed_texts"):
            return await self._embedding_service.embed_texts(texts)
        return [await self._embedding_service.embed_text(text) for text in texts]

    def _vector_entity_id(self, parent_id: str, chunk: ChunkedText) -> str:
        if chunk.chunk_id == parent_id or "::" in chunk.chunk_id:
            return chunk.chunk_id
        return f"{parent_id}::{chunk.chunk_id}"


__all__ = [
    "EmbeddingPipelineItem",
    "EmbeddingPipelineResult",
    "MemoryEmbeddingPipeline",
]
