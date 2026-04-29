"""Embedding helper functions for L3 summary storage."""
from __future__ import annotations

from typing import Any, Dict

import aiosqlite

from ..embedding.chunking import ChunkedText, chunk_text
from ..embedding.embedding_pipeline import MemoryEmbeddingPipeline
from ..embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ..embedding.embedding_text_builders import build_l3_embedding_text
from ..embedding.sqlite_vec_index import SqliteVecIndex, VectorSearchHit

EMBEDDING_TEXT_BUILDER_VERSION = "l3_summary_v1"


def build_embedding_pipeline(
    *,
    embedding_service: MemoryEmbeddingService | None,
    vector_index: SqliteVecIndex | None,
) -> MemoryEmbeddingPipeline | None:
    if embedding_service is None or vector_index is None:
        return None
    return MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
    )


def get_embedding_text(summary: Dict[str, Any]) -> str:
    return build_l3_embedding_text(summary)


def build_summary_embedding_chunks(summary: Dict[str, Any]) -> list[ChunkedText]:
    return chunk_text(get_embedding_text(summary))


def chunk_id_for_summary(summary_id: str, chunk_index: int) -> str:
    return f"{summary_id}::chunk-{chunk_index}"


def profile_from_embedding_result(
    *,
    embedding_service: MemoryEmbeddingService | None,
    result: Any,
) -> EmbeddingProfile:
    getter = getattr(embedding_service, "profile_from_result", None)
    if callable(getter):
        return getter(result, text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION)
    return EmbeddingProfile.build(
        provider_name="unknown",
        model_name=result.model_name,
        dimension=result.dimension,
        text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
    )


def fold_summary_chunk_hits(
    *,
    hits: list[VectorSearchHit],
    chunk_rows: list[aiosqlite.Row],
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    chunk_by_id = {str(row["chunk_id"]): row for row in chunk_rows}
    summary_ids: list[str] = []
    matched_chunks: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        row = chunk_by_id.get(hit.entity_id)
        if row is None:
            continue
        summary_id = str(row["summary_id"])
        if summary_id not in matched_chunks:
            summary_ids.append(summary_id)
            matched_chunks[summary_id] = []
        matched_chunks[summary_id].append(
            {
                "chunk_id": str(row["chunk_id"]),
                "chunk_index": int(row["chunk_index"]),
                "text": str(row["chunk_text"]),
                "char_start": int(row["char_start"]),
                "char_end": int(row["char_end"]),
                "distance": float(hit.distance),
            }
        )
    return summary_ids, matched_chunks