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


@dataclass(slots=True)
class _EmbeddingWriteBatch:
    results: list[EmbeddingPipelineResult]
    vector_items: list[dict[str, Any]]


class MemoryEmbeddingPipeline:
    """Embed prepared chunk texts and persist them through one vector index."""

    def __init__(
        self,
        *,
        embedding_service: MemoryEmbeddingService,
        vector_index: SqliteVecIndex,
        text_builder_version: str | None = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._vector_index = vector_index
        self._text_builder_version = text_builder_version

    async def upsert_items(
        self, items: list[EmbeddingPipelineItem]
    ) -> list[EmbeddingPipelineResult]:
        """Embed *items* and write all chunk vectors, with single-row fallback."""
        results = await self.prepare_items(items)
        return await self.persist_results(results)

    async def prepare_items(
        self,
        items: list[EmbeddingPipelineItem],
    ) -> list[EmbeddingPipelineResult]:
        """Compute embeddings without mutating the vector index."""
        prepared_items = [item for item in items if item.chunks]
        if not prepared_items:
            return []

        texts = [chunk.text for item in prepared_items for chunk in item.chunks]
        embeddings = await self._embed_texts(texts)
        if not embeddings:
            return []
        return self._build_successful_results(
            items=prepared_items,
            embeddings=embeddings,
            embedded_at=time.time(),
        )

    async def persist_results(
        self,
        results: list[EmbeddingPipelineResult],
    ) -> list[EmbeddingPipelineResult]:
        """Persist previously computed results through the vector index."""
        write_batch = _EmbeddingWriteBatch(
            results=list(results),
            vector_items=self._batch_vector_items(results),
        )
        if not write_batch.vector_items:
            return []
        return await self._persist_write_batch(write_batch)

    def _build_successful_results(
        self,
        *,
        items: list[EmbeddingPipelineItem],
        embeddings: list[EmbeddingResult | None],
        embedded_at: float,
    ) -> list[EmbeddingPipelineResult]:
        results: list[EmbeddingPipelineResult] = []
        embedding_index = 0
        for item in items:
            chunk_embeddings = embeddings[embedding_index : embedding_index + len(item.chunks)]
            embedding_index += len(item.chunks)
            typed_embeddings = self._typed_chunk_embeddings(item, chunk_embeddings)
            if typed_embeddings is None:
                continue
            results.append(
                EmbeddingPipelineResult(
                    parent_id=item.parent_id,
                    chunks=item.chunks,
                    embeddings=typed_embeddings,
                    metadata=dict(item.metadata),
                    payload=item.payload,
                    embedded_at=embedded_at,
                )
            )
        return results

    def _typed_chunk_embeddings(
        self,
        item: EmbeddingPipelineItem,
        chunk_embeddings: list[EmbeddingResult | None],
    ) -> list[EmbeddingResult] | None:
        if len(chunk_embeddings) != len(item.chunks):
            return None
        typed_embeddings: list[EmbeddingResult] = []
        for embedding in chunk_embeddings:
            if embedding is None:
                return None
            typed_embeddings.append(self._result_for_index(embedding))
        return typed_embeddings

    def _batch_vector_items(
        self,
        results: list[EmbeddingPipelineResult],
    ) -> list[dict[str, Any]]:
        vector_items: list[dict[str, Any]] = []
        for result in results:
            for chunk, embedding in zip(result.chunks, result.embeddings):
                metadata = dict(result.metadata)
                metadata.setdefault("chunk_index", chunk.chunk_index)
                vector_items.append(
                    {
                        "entity_id": self._vector_entity_id(result.parent_id, chunk),
                        "embedding": embedding,
                        "metadata": metadata,
                    }
                )
        return vector_items

    async def _persist_write_batch(
        self,
        write_batch: _EmbeddingWriteBatch,
    ) -> list[EmbeddingPipelineResult]:
        try:
            await self._vector_index.upsert_many(write_batch.vector_items)
            return write_batch.results
        except Exception as exc:
            logger.warning(
                "Failed batch upsert for memory embeddings, falling back to single-row writes: %s",
                exc,
            )
        return await self._fallback_upsert_results(write_batch.results)

    async def _fallback_upsert_results(
        self,
        results: list[EmbeddingPipelineResult],
    ) -> list[EmbeddingPipelineResult]:
        persisted_results: list[EmbeddingPipelineResult] = []
        for result in results:
            try:
                for vector_item in self._single_row_vector_items(result):
                    await self._vector_index.upsert(
                        entity_id=str(vector_item["entity_id"]),
                        embedding=vector_item["embedding"],
                        metadata=vector_item.get("metadata"),
                    )
                persisted_results.append(result)
            except Exception as item_exc:
                logger.warning(
                    "Failed to upsert memory embedding chunks for %s: %s",
                    result.parent_id,
                    item_exc,
                )
        return persisted_results

    def _single_row_vector_items(
        self,
        result: EmbeddingPipelineResult,
    ) -> list[dict[str, Any]]:
        return [
            {
                "entity_id": self._vector_entity_id(result.parent_id, chunk),
                "embedding": embedding,
                "metadata": {**result.metadata, "chunk_index": chunk.chunk_index},
            }
            for chunk, embedding in zip(result.chunks, result.embeddings)
        ]

    async def _embed_texts(self, texts: list[str]) -> list[EmbeddingResult | None]:
        if hasattr(self._embedding_service, "embed_texts"):
            return await self._embedding_service.embed_texts(texts)
        return [await self._embedding_service.embed_text(text) for text in texts]

    def _result_for_index(self, embedding: EmbeddingResult) -> EmbeddingResult:
        if not self._text_builder_version:
            return embedding
        identity_builder = getattr(self._embedding_service, "result_for_index", None)
        if callable(identity_builder):
            return identity_builder(embedding, text_builder_version=self._text_builder_version)
        return embedding

    def _vector_entity_id(self, parent_id: str, chunk: ChunkedText) -> str:
        if chunk.chunk_id == parent_id or "::" in chunk.chunk_id:
            return chunk.chunk_id
        return f"{parent_id}::{chunk.chunk_id}"


__all__ = [
    "EmbeddingPipelineItem",
    "EmbeddingPipelineResult",
    "MemoryEmbeddingPipeline",
]
