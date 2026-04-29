"""Embedding lifecycle operations for L4 procedural skills."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.embedding_pipeline import EmbeddingPipelineItem
from ...embedding.embedding_service import MemoryEmbeddingService
from ...embedding.sqlite_vec_index import SqliteVecIndex
from ..retrieval.search import ranked_semantic_skills
from ..storage.schema import (
    EMBEDDING_STATUS_DISABLED,
    EMBEDDING_STATUS_READY,
    SKILL_CHUNKS_TABLE,
)
from .skills import (
    build_embedding_pipeline,
    build_skill_embedding_chunks,
    build_skill_embedding_text,
    fetch_skill_chunk_rows_by_ids,
    fold_skill_chunk_hits,
    profile_from_embedding_result,
    replace_skill_chunks,
    update_skill_embedding_state,
)

logger = logging.getLogger(__name__)


class L4SkillEmbeddingMixin:
    """Manage L4 skill embeddings and semantic retrieval support."""

    db_path: str
    _embedding_service: MemoryEmbeddingService | None
    _embedding_queue: asyncio.Queue[dict[str, Any] | None] | None
    _embedding_worker: asyncio.Task[None] | None
    _vector_index: SqliteVecIndex | None

    async def initialize(self) -> None:
        raise NotImplementedError

    def _vectors_enabled(self) -> bool:
        raise NotImplementedError

    def _async_embeddings_enabled(self) -> bool:
        raise NotImplementedError

    async def rebuild_embeddings(self, *, batch_size: int = 100) -> int:
        """Rebuild all persisted L4 skill embeddings from parent rows."""
        await self.initialize()
        normalized_batch_size = max(1, int(batch_size))
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None:
            return 0

        await self._vector_index.clear()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(f"DELETE FROM {SKILL_CHUNKS_TABLE}")
            await db.execute(
                """
                UPDATE procedural_skills
                SET embedding_status = ?, embedding_profile_id = NULL, embedding_chunk_count = 0, last_embedded_at = NULL
                """,
                (EMBEDDING_STATUS_DISABLED,),
            )
            await db.commit()

        processed = 0
        offset = 0
        while True:
            async with sqlite_connection_async(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT skill_id, skill_name, skill_category, optimized_prompt
                    FROM procedural_skills
                    ORDER BY updated_at DESC, skill_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (normalized_batch_size, offset),
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                break
            for row in rows:
                await self._maybe_upsert_skill_embedding(
                    skill_id=str(row["skill_id"]),
                    skill_name=str(row["skill_name"]),
                    skill_category=str(row["skill_category"]),
                    optimized_prompt=row["optimized_prompt"],
                )
            processed += len(rows)
            offset += len(rows)
        return processed

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for higher-level reporting."""
        return {
            "db_path": self.db_path,
            "vector_enabled": self._vectors_enabled(),
            "async_embeddings": self._async_embeddings_enabled(),
            "embedding_queue_size": self._embedding_queue.qsize() if self._embedding_queue is not None else 0,
            "embedding_worker_running": bool(self._embedding_worker is not None and not self._embedding_worker.done()),
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
        pipeline = build_embedding_pipeline(
            embedding_service=self._embedding_service,
            vector_index=self._vector_index,
        )
        if pipeline is None:
            return
        text = build_skill_embedding_text(
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
        )
        results = await pipeline.upsert_items(
            [
                EmbeddingPipelineItem(
                    parent_id=skill_id,
                    chunks=build_skill_embedding_chunks(
                        skill_id=skill_id,
                        text=text,
                    ),
                    metadata={
                        "skill_id": skill_id,
                        "skill_name": skill_name,
                        "skill_category": skill_category,
                    },
                    payload={
                        "skill_id": skill_id,
                    },
                )
            ]
        )
        if not results:
            return
        result = results[0]
        profile = profile_from_embedding_result(
            embedding_service=self._embedding_service,
            result=result.embeddings[0],
        )
        await replace_skill_chunks(
            db_path=self.db_path,
            skill_id=skill_id,
            chunks=result.chunks,
            embedded_at=result.embedded_at,
        )
        await update_skill_embedding_state(
            db_path=self.db_path,
            skill_id=skill_id,
            status=EMBEDDING_STATUS_READY,
            profile_id=profile.profile_id,
            chunk_count=len(result.chunks),
            embedded_at=result.embedded_at,
        )

    async def _semantic_query_strategies(self, *, query: str, limit: int) -> List[Dict[str, Any]]:
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None or not query.strip():
            return []
        embedding = await self._embedding_service.embed_text(query)
        if embedding is None:
            return []
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
                f"SELECT * FROM procedural_skills WHERE skill_id IN ({placeholders})",
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
            try:
                await self._maybe_upsert_skill_embedding(
                    skill_id=str(item["skill_id"]),
                    skill_name=str(item["skill_name"]),
                    skill_category=str(item["skill_category"]),
                    optimized_prompt=item.get("optimized_prompt"),
                )
            finally:
                self._embedding_queue.task_done()


__all__ = ["L4SkillEmbeddingMixin"]