"""Embedding lifecycle operations for L4 procedural skills."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.embedding_pipeline import (
    EmbeddingPipelineItem,
    EmbeddingPipelineResult,
    verify_active_rebuild_profile,
)
from ...embedding.embedding_service import MemoryEmbeddingService
from ...embedding.sqlite_vec_index import SqliteVecIndex
from ...operation_barrier import optional_operation_guard
from ..retrieval.search import ranked_semantic_skills
from ..source_event_governance import active_skill_predicate
from ..storage.schema import (
    EMBEDDING_STATUS_READY,
    SKILL_CHUNKS_TABLE,
)
from .skills import (
    EMBEDDING_TEXT_BUILDER_VERSION,
    build_embedding_pipeline,
    build_skill_embedding_chunks,
    build_skill_embedding_text,
    fetch_skill_chunk_rows_by_ids,
    fold_skill_chunk_hits,
    profile_from_embedding_result,
)

logger = logging.getLogger(__name__)


class L4SkillEmbeddingMixin:
    """Manage L4 skill embeddings and semantic retrieval support."""

    db_path: str
    _embedding_service: MemoryEmbeddingService | None
    _embedding_queue: asyncio.Queue[dict[str, Any] | None] | None
    _embedding_worker: asyncio.Task[None] | None
    _embedding_active_count: int
    _vector_index: SqliteVecIndex | None
    _operation_guard_factory: Callable[[], Any] | None

    async def initialize(self) -> None:
        raise NotImplementedError

    def _vectors_enabled(self) -> bool:
        raise NotImplementedError

    def _async_embeddings_enabled(self) -> bool:
        raise NotImplementedError

    def embedding_mutation_guard(self) -> Any:
        raise NotImplementedError

    async def rebuild_embeddings(
        self,
        *,
        batch_size: int = 100,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> int:
        """Rebuild all persisted L4 skill embeddings from parent rows."""
        await self.initialize()
        normalized_batch_size = max(1, int(batch_size))
        if (
            not self._vectors_enabled()
            or self._embedding_service is None
            or self._vector_index is None
        ):
            return 0

        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM procedural_skills"
            ) as cursor:
                row = await cursor.fetchone()
        high_water_rowid = int(row[0] or 0) if row is not None else 0

        processed = 0
        last_rowid = 0
        async with self._vector_index.rebuild_session():
            while last_rowid < high_water_rowid:
                async with sqlite_connection_async(self.db_path) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        f"""
                        SELECT rowid AS rebuild_rowid, skill_id, skill_name,
                            skill_category, optimized_prompt
                        FROM procedural_skills AS skills
                        WHERE rowid > ? AND rowid <= ?
                          AND {active_skill_predicate("skills")}
                        ORDER BY rowid ASC
                        LIMIT ?
                        """,
                        (last_rowid, high_water_rowid, normalized_batch_size),
                    ) as cursor:
                        rows = await cursor.fetchall()
                if not rows:
                    break
                last_rowid = int(rows[-1]["rebuild_rowid"])
                for row in rows:
                    await self._maybe_upsert_skill_embedding(
                        skill_id=str(row["skill_id"]),
                        skill_name=str(row["skill_name"]),
                        skill_category=str(row["skill_category"]),
                        optimized_prompt=row["optimized_prompt"],
                    )
                processed += len(rows)
                if progress_callback is not None:
                    await progress_callback(processed)
            await self._vector_index.prune_orphans(
                valid_entity_query=f"""
                    SELECT chunks.chunk_id AS entity_id
                    FROM {SKILL_CHUNKS_TABLE} AS chunks
                    JOIN procedural_skills AS skills
                      ON skills.skill_id = chunks.skill_id
                    WHERE {active_skill_predicate("skills")}
                """,
                mutation_guard_factory=self.embedding_mutation_guard,
            )
            verify_active_rebuild_profile(
                embedding_service=self._embedding_service,
                vector_index=self._vector_index,
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
            )
        return processed

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for higher-level reporting."""
        return {
            "db_path": self.db_path,
            "vector_enabled": self._vectors_enabled(),
            "async_embeddings": self._async_embeddings_enabled(),
            "embedding_queue_size": (
                self._embedding_queue.qsize() if self._embedding_queue is not None else 0
            ),
            "embedding_active_count": int(getattr(self, "_embedding_active_count", 0)),
            "embedding_worker_running": bool(
                self._embedding_worker is not None and not self._embedding_worker.done()
            ),
        }

    async def _maybe_upsert_skill_embedding(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        optimized_prompt: Optional[str],
    ) -> None:
        if not self._vectors_enabled():
            return
        snapshot = await self._skill_embedding_snapshot(
            skill_id=skill_id,
            display_skill_name=skill_name,
        )
        if snapshot is None:
            return
        pipeline = build_embedding_pipeline(
            embedding_service=self._embedding_service,
            vector_index=self._vector_index,
        )
        if pipeline is None:
            return
        text = build_skill_embedding_text(
            skill_name=str(snapshot["display_skill_name"]),
            skill_category=str(snapshot["skill_category"]),
            optimized_prompt=snapshot.get("optimized_prompt"),
        )
        prepared_results = await pipeline.prepare_items(
            [
                EmbeddingPipelineItem(
                    parent_id=skill_id,
                    chunks=build_skill_embedding_chunks(
                        skill_id=skill_id,
                        text=text,
                    ),
                    metadata={
                        "skill_id": skill_id,
                        "skill_name": str(snapshot["display_skill_name"]),
                        "skill_category": str(snapshot["skill_category"]),
                    },
                    payload=snapshot,
                )
            ]
        )
        if not prepared_results:
            return
        async with optional_operation_guard(self._operation_guard_factory):
            async with self.embedding_mutation_guard():
                if not await self._skill_embedding_snapshot_is_current(snapshot):
                    return
                results = await pipeline.persist_results(prepared_results)
                if not results:
                    return
                result = results[0]
                published = await self._publish_skill_embedding_result(result)
                if published:
                    return
                if self._vector_index is not None:
                    for chunk, embedding in zip(
                        result.chunks,
                        result.embeddings,
                        strict=True,
                    ):
                        await self._vector_index.delete_embedding(
                            entity_id=chunk.chunk_id,
                            embedding=embedding,
                        )

    async def _skill_embedding_snapshot(
        self,
        *,
        skill_id: str,
        display_skill_name: str,
    ) -> dict[str, Any] | None:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT skills.skill_id, skills.skill_name, skills.skill_category,
                       skills.optimized_prompt, skills.updated_at
                FROM procedural_skills AS skills
                WHERE skills.skill_id = ?
                  AND {active_skill_predicate("skills")}
                """,
                (skill_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "skill_id": str(row["skill_id"]),
            "stored_skill_name": str(row["skill_name"]),
            "display_skill_name": str(display_skill_name),
            "skill_category": str(row["skill_category"]),
            "optimized_prompt": row["optimized_prompt"],
            "updated_at": float(row["updated_at"]),
        }

    async def _skill_embedding_snapshot_is_current(
        self,
        snapshot: dict[str, Any],
    ) -> bool:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT skills.skill_name, skills.skill_category,
                       skills.optimized_prompt, skills.updated_at
                FROM procedural_skills AS skills
                WHERE skills.skill_id = ?
                  AND {active_skill_predicate("skills")}
                """,
                (str(snapshot["skill_id"]),),
            ) as cursor:
                row = await cursor.fetchone()
        return _skill_embedding_parent_is_current(row, snapshot)

    async def _publish_skill_embedding_result(
        self,
        result: EmbeddingPipelineResult,
    ) -> bool:
        snapshot = dict(result.payload)
        profile = profile_from_embedding_result(
            embedding_service=self._embedding_service,
            result=result.embeddings[0],
        )
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    f"""
                    SELECT skills.skill_name, skills.skill_category,
                           skills.optimized_prompt, skills.updated_at
                    FROM procedural_skills AS skills
                    WHERE skills.skill_id = ?
                      AND {active_skill_predicate("skills")}
                    """,
                    (result.parent_id,),
                ) as cursor:
                    current = await cursor.fetchone()
                if not _skill_embedding_parent_is_current(current, snapshot):
                    await db.rollback()
                    return False
                await db.execute(
                    f"DELETE FROM {SKILL_CHUNKS_TABLE} WHERE skill_id = ?",
                    (result.parent_id,),
                )
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
                            result.parent_id,
                            chunk.chunk_index,
                            chunk.text,
                            chunk.char_start,
                            chunk.char_end,
                            chunk.token_estimate,
                            result.embedded_at,
                            result.embedded_at,
                        )
                        for chunk in result.chunks
                    ],
                )
                await db.execute(
                    """
                    UPDATE procedural_skills
                    SET embedding_status = ?, embedding_profile_id = ?,
                        embedding_chunk_count = ?, last_embedded_at = ?
                    WHERE skill_id = ?
                    """,
                    (
                        EMBEDDING_STATUS_READY,
                        profile.profile_id,
                        len(result.chunks),
                        result.embedded_at,
                        result.parent_id,
                    ),
                )
                await db.commit()
                return True
            except Exception:
                await db.rollback()
                raise

    async def _semantic_query_strategies(self, *, query: str, limit: int) -> List[Dict[str, Any]]:
        if (
            not self._vectors_enabled()
            or self._embedding_service is None
            or self._vector_index is None
            or not query.strip()
        ):
            return []
        embedding = await self._embedding_service.embed_text(query)
        if embedding is None:
            return []
        embedding = self._embedding_service.result_for_index(
            embedding,
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )
        try:
            hits = await self._vector_index.search(embedding=embedding, limit=max(limit * 3, 10))
        except Exception as exc:
            logger.warning("Failed semantic search over procedural skills: %s", exc)
            return []
        if not hits:
            return []
        chunk_rows = await fetch_skill_chunk_rows_by_ids(
            db_path=self.db_path,
            chunk_ids=[hit.entity_id for hit in hits],
        )
        skill_ids, matched_chunks = fold_skill_chunk_hits(hits=hits, chunk_rows=chunk_rows)
        if not skill_ids:
            return []
        placeholders = ", ".join("?" for _ in skill_ids)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT skills.*
                FROM procedural_skills AS skills
                WHERE skills.skill_id IN ({placeholders})
                  AND {active_skill_predicate("skills")}
                """,
                tuple(skill_ids),
            ) as cursor:
                rows = await cursor.fetchall()
        return ranked_semantic_skills(
            rows=rows,
            skill_ids=skill_ids,
            matched_chunks=matched_chunks,
            limit=limit,
        )

    async def _schedule_skill_embedding(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        optimized_prompt: Optional[str],
    ) -> None:
        if not self._vectors_enabled():
            return
        if self._embedding_queue is not None and self._async_embeddings_enabled():
            await self._embedding_queue.put(
                {
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "skill_category": skill_category,
                    "optimized_prompt": optimized_prompt,
                }
            )
            return
        await self._maybe_upsert_skill_embedding(
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
        )

    async def _run_embedding_worker(self) -> None:
        if self._embedding_queue is None:
            return
        while True:
            item = await self._embedding_queue.get()
            if item is None:
                self._embedding_queue.task_done()
                break
            self._embedding_active_count += 1
            try:
                await self._maybe_upsert_skill_embedding(
                    skill_id=str(item["skill_id"]),
                    skill_name=str(item["skill_name"]),
                    skill_category=str(item["skill_category"]),
                    optimized_prompt=item.get("optimized_prompt"),
                )
            finally:
                self._embedding_active_count = max(0, self._embedding_active_count - 1)
                self._embedding_queue.task_done()


__all__ = ["L4SkillEmbeddingMixin"]


def _skill_embedding_parent_is_current(
    current: aiosqlite.Row | None,
    snapshot: dict[str, Any],
) -> bool:
    if current is None:
        return False
    return (
        str(current["skill_name"]) == str(snapshot["stored_skill_name"])
        and str(current["skill_category"]) == str(snapshot["skill_category"])
        and current["optimized_prompt"] == snapshot.get("optimized_prompt")
    )
