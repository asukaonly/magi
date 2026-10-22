"""Chunk row persistence helpers for L1 event embeddings."""

from __future__ import annotations

from typing import cast

from ...embedding.chunking import ChunkedText, chunk_sentences
from ...event_contracts import MemoryEvent
from .common import L1EventEmbeddingHostProtocol
from ..embedding_contracts import EventChunkRecord


class L1EventEmbeddingChunkMixin:
    """Own L1 event embedding chunk construction and storage."""

    def _build_event_embedding_chunks(self, event: MemoryEvent) -> list[ChunkedText]:
        host = cast(L1EventEmbeddingHostProtocol, self)
        return cast(list[ChunkedText], chunk_sentences(host.get_embedding_text(event)))

    def _chunk_id_for_event(self, event_id: str, chunk_index: int) -> str:
        return f"{event_id}::chunk-{chunk_index}"

    async def _fetch_chunk_rows_by_ids(self, chunk_ids: list[str]) -> list[EventChunkRecord]:
        host = cast(L1EventEmbeddingHostProtocol, self)
        return await host.event_repository.fetch_embedding_chunks(chunk_ids)
