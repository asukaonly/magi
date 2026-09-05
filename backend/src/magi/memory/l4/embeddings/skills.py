"""Embedding helper functions for L4 procedural memory."""

from __future__ import annotations

from typing import Any, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.chunking import ChunkedText, chunk_text
from ...embedding.embedding_pipeline import MemoryEmbeddingPipeline
from ...embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ...embedding.embedding_text_builders import build_l4_embedding_text
from ...embedding.sqlite_vec_index import SqliteVecIndex, VectorSearchHit
from ..source_event_governance import active_skill_predicate
from ..storage.schema import EMBEDDING_TEXT_BUILDER_VERSION, SKILL_CHUNKS_TABLE


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


def build_skill_embedding_text(
    *,
    skill_name: str,
    skill_category: str,
    optimized_prompt: str | None,
) -> str:
    return cast(
        str,
        build_l4_embedding_text(
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
        ),
    )


def chunk_id_for_skill(skill_id: str, chunk_index: int) -> str:
    return f"{skill_id}::chunk-{chunk_index}"


def build_skill_embedding_chunks(*, skill_id: str, text: str) -> list[ChunkedText]:
    chunks = chunk_text(text)
    return [
        ChunkedText(
            chunk_id=chunk_id_for_skill(skill_id, chunk.chunk_index),
            text=chunk.text,
            chunk_index=chunk.chunk_index,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            token_estimate=chunk.token_estimate,
        )
        for chunk in chunks
    ]


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


def fold_skill_chunk_hits(
    *,
    hits: list[VectorSearchHit],
    chunk_rows: list[aiosqlite.Row],
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    chunk_by_id = {str(row["chunk_id"]): row for row in chunk_rows}
    skill_ids: list[str] = []
    matched_chunks: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        row = chunk_by_id.get(hit.entity_id)
        if row is None:
            continue
        skill_id = str(row["skill_id"])
        if skill_id not in matched_chunks:
            skill_ids.append(skill_id)
            matched_chunks[skill_id] = []
        matched_chunks[skill_id].append(
            {
                "chunk_id": str(row["chunk_id"]),
                "chunk_index": int(row["chunk_index"]),
                "text": str(row["chunk_text"]),
                "char_start": int(row["char_start"]),
                "char_end": int(row["char_end"]),
                "distance": float(hit.distance),
            }
        )
    return skill_ids, matched_chunks


async def replace_skill_chunks(
    *,
    db_path: str,
    skill_id: str,
    chunks: list[ChunkedText],
    embedded_at: float,
) -> None:
    async with sqlite_connection_async(db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute(
            f"DELETE FROM {SKILL_CHUNKS_TABLE} WHERE skill_id = ?",
            (skill_id,),
        )
        async with db.execute(
            f"""
            SELECT 1
            FROM procedural_skills AS skills
            WHERE skills.skill_id = ? AND {active_skill_predicate("skills")}
            """,
            (skill_id,),
        ) as cursor:
            active = await cursor.fetchone()
        if active is None:
            await db.commit()
            return
        await db.executemany(
            f"""
            INSERT INTO {SKILL_CHUNKS_TABLE}(
                chunk_id, skill_id, chunk_index, chunk_text, char_start, char_end,
                token_estimate, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    skill_id,
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


async def update_skill_embedding_state(
    *,
    db_path: str,
    skill_id: str,
    status: str,
    profile_id: str | None,
    chunk_count: int,
    embedded_at: float,
) -> None:
    async with sqlite_connection_async(db_path) as db:
        await db.execute(
            f"""
            UPDATE procedural_skills
            SET embedding_status = ?, embedding_profile_id = ?, embedding_chunk_count = ?, last_embedded_at = ?, updated_at = updated_at
            WHERE skill_id = ?
              AND {active_skill_predicate("procedural_skills")}
            """,
            (status, profile_id, int(chunk_count), float(embedded_at), skill_id),
        )
        await db.commit()


async def fetch_skill_chunk_rows_by_ids(
    *, db_path: str, chunk_ids: list[str]
) -> list[aiosqlite.Row]:
    if not chunk_ids:
        return []
    placeholders = ", ".join("?" for _ in chunk_ids)
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT chunks.chunk_id, chunks.skill_id, chunks.chunk_index,
                   chunks.chunk_text, chunks.char_start, chunks.char_end
            FROM {SKILL_CHUNKS_TABLE} AS chunks
            JOIN procedural_skills AS skills ON skills.skill_id = chunks.skill_id
            WHERE chunks.chunk_id IN ({placeholders})
              AND {active_skill_predicate("skills")}
              AND skills.embedding_status = 'ready'
            """,
            tuple(chunk_ids),
        ) as cursor:
            return cast(list[aiosqlite.Row], await cursor.fetchall())
