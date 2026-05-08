"""Embedding helper functions for L3 summary storage."""

from __future__ import annotations

from typing import Any, Dict, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.chunking import ChunkedText, chunk_text
from ...embedding.embedding_pipeline import MemoryEmbeddingPipeline
from ...embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ...embedding.embedding_text_builders import build_l3_embedding_text
from ...embedding.sqlite_vec_index import SqliteVecIndex, VectorSearchHit
from ..storage.schema import SUMMARY_CHUNKS_TABLE

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
        text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
    )


def get_embedding_text(summary: Dict[str, Any]) -> str:
    return cast(str, build_l3_embedding_text(summary))


def build_summary_embedding_chunks(summary: Dict[str, Any]) -> list[ChunkedText]:
    return cast(list[ChunkedText], chunk_text(get_embedding_text(summary)))


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


async def replace_summary_chunks(
    *,
    db_path: str,
    entries: list[tuple[Dict[str, Any], list[ChunkedText]]],
    embedded_at: float,
) -> None:
    if not entries:
        return
    async with sqlite_connection_async(db_path) as db:
        for summary, chunks in entries:
            summary_id = str(summary["summary_id"])
            await db.execute(
                f"DELETE FROM {SUMMARY_CHUNKS_TABLE} WHERE summary_id = ?",
                (summary_id,),
            )
            await db.executemany(
                f"""
                INSERT INTO {SUMMARY_CHUNKS_TABLE}(
                    chunk_id, summary_id, chunk_index, chunk_text, char_start, char_end,
                    token_estimate, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk_id_for_summary(summary_id, chunk.chunk_index),
                        summary_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.token_estimate,
                        embedded_at,
                        embedded_at,
                    )
                    for chunk in chunks
                ],
            )
        await db.commit()


async def update_summary_embedding_state(
    *,
    db_path: str,
    summary_id: str,
    status: str,
    profile_id: str | None,
    chunk_count: int,
    embedded_at: float,
) -> None:
    async with sqlite_connection_async(db_path) as db:
        await db.execute(
            """
            UPDATE summaries
            SET embedding_status = ?, embedding_profile_id = ?, embedding_chunk_count = ?, last_embedded_at = ?, updated_at = updated_at
            WHERE summary_id = ?
            """,
            (status, profile_id, int(chunk_count), float(embedded_at), summary_id),
        )
        await db.commit()


async def fetch_summary_chunk_rows_by_ids(
    *, db_path: str, chunk_ids: list[str]
) -> list[aiosqlite.Row]:
    if not chunk_ids:
        return []
    placeholders = ", ".join("?" for _ in chunk_ids)
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT chunk_id, summary_id, chunk_index, chunk_text, char_start, char_end
            FROM {SUMMARY_CHUNKS_TABLE}
            WHERE chunk_id IN ({placeholders})
            """,
            tuple(chunk_ids),
        ) as cursor:
            return cast(list[aiosqlite.Row], await cursor.fetchall())
