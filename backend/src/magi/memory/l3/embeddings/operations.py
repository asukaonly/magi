"""Embedding operations for L3 summary storage."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.embedding_pipeline import EmbeddingPipelineItem
from ...embedding.embedding_service import MemoryEmbeddingService
from ...embedding.sqlite_vec_index import SqliteVecIndex
from ..retrieval.search import ranked_vector_summaries
from ..storage.schema import (
    EMBEDDING_STATUS_DISABLED,
    EMBEDDING_STATUS_READY,
    SUMMARY_CHUNKS_TABLE,
)
from .summaries import (
    EMBEDDING_TEXT_BUILDER_VERSION,
    build_embedding_pipeline,
    build_summary_embedding_chunks,
    fetch_summary_chunk_rows_by_ids,
    fold_summary_chunk_hits,
    profile_from_embedding_result,
    replace_summary_chunks,
    update_summary_embedding_state,
)

logger = logging.getLogger(__name__)


class _L3SummaryEmbeddingHostProtocol(Protocol):
    db_path: str
    _embedding_service: MemoryEmbeddingService | None
    _vector_index: SqliteVecIndex | None
    _embedding_queue: asyncio.Queue[Dict[str, Any] | None] | None
    _embedding_active_count: int
    _embedding_batch_size: int
    _embedding_batch_wait_seconds: float

    async def initialize(self) -> None: ...

    def _vectors_enabled(self) -> bool: ...

    def _async_embeddings_enabled(self) -> bool: ...

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    async def fetch_by_ids(
        self,
        summary_ids: List[str],
        *,
        summary_type: Optional[str] = None,
        summary_category: Optional[str] = None,
    ) -> List[Dict[str, Any]]: ...


class L3SummaryEmbeddingMixin:
    """Embedding rebuild, vector upsert, and semantic search helpers."""

    async def rebuild_embeddings(
        self,
        *,
        batch_size: int = 100,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> int:
        """Rebuild all persisted L3 summary embeddings from parent rows."""
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        await host.initialize()
        normalized_batch_size = max(1, int(batch_size))
        if (
            not host._vectors_enabled()
            or host._embedding_service is None
            or host._vector_index is None
        ):
            return 0

        await host._vector_index.clear()
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute(f"DELETE FROM {SUMMARY_CHUNKS_TABLE}")
            await db.execute(
                """
                UPDATE summaries
                SET embedding_status = ?, embedding_profile_id = NULL, embedding_chunk_count = 0, last_embedded_at = NULL
                """,
                (EMBEDDING_STATUS_DISABLED,),
            )
            await db.commit()

        processed = 0
        offset = 0
        while True:
            async with sqlite_connection_async(host.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT *
                    FROM summaries
                    WHERE derivation_state = 'current'
                    ORDER BY updated_at DESC, summary_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (normalized_batch_size, offset),
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                break
            summaries = [host._row_to_dict(row) for row in rows]
            await self._maybe_upsert_summary_embeddings(summaries)
            processed += len(summaries)
            offset += len(rows)
            if progress_callback is not None:
                await progress_callback(processed)
        return processed

    async def _maybe_upsert_summary_embedding(self, summary: Dict[str, Any]) -> None:
        await self._maybe_upsert_summary_embeddings([summary])

    async def _maybe_upsert_summary_embeddings(self, summaries: List[Dict[str, Any]]) -> None:
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        if not host._vectors_enabled():
            return
        pipeline = build_embedding_pipeline(
            embedding_service=host._embedding_service,
            vector_index=host._vector_index,
        )
        if pipeline is None:
            return
        results = await pipeline.upsert_items(
            [
                EmbeddingPipelineItem(
                    parent_id=str(summary["summary_id"]),
                    chunks=build_summary_embedding_chunks(summary),
                    metadata={
                        "summary_id": str(summary["summary_id"]),
                        "summary_type": summary.get("summary_type"),
                        "summary_category": summary.get("summary_category"),
                    },
                    payload=summary,
                )
                for summary in summaries
            ]
        )
        if not results:
            return
        embedded_at = results[0].embedded_at
        await replace_summary_chunks(
            db_path=host.db_path,
            entries=[(result.payload, result.chunks) for result in results],
            embedded_at=embedded_at,
        )
        for result in results:
            summary = result.payload
            profile = profile_from_embedding_result(
                embedding_service=host._embedding_service,
                result=result.embeddings[0],
            )
            try:
                await update_summary_embedding_state(
                    db_path=host.db_path,
                    summary_id=result.parent_id,
                    status=EMBEDDING_STATUS_READY,
                    profile_id=profile.profile_id,
                    chunk_count=len(result.chunks),
                    embedded_at=result.embedded_at,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to update summary embedding state for %s: %s",
                    summary.get("summary_id"),
                    exc,
                )

    async def vector_search(
        self,
        *,
        query: str,
        summary_type: Optional[str] = None,
        summary_category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
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
            hits = await host._vector_index.search(embedding=embedding, limit=max(limit * 3, 10))
        except Exception as exc:
            logger.warning("Failed semantic search over summaries: %s", exc)
            return []
        if not hits:
            return []
        chunk_rows = await fetch_summary_chunk_rows_by_ids(
            db_path=host.db_path,
            chunk_ids=[hit.entity_id for hit in hits],
        )
        summary_ids, matched_chunks = fold_summary_chunk_hits(hits=hits, chunk_rows=chunk_rows)
        if not summary_ids:
            return []
        summaries = await host.fetch_by_ids(
            summary_ids,
            summary_type=summary_type,
            summary_category=summary_category,
        )
        return ranked_vector_summaries(
            summaries=summaries,
            summary_ids=summary_ids,
            matched_chunks=matched_chunks,
            limit=limit,
        )

    async def _schedule_summary_embedding(self, summary: Dict[str, Any]) -> None:
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        if not host._vectors_enabled():
            return
        if host._embedding_queue is not None and host._async_embeddings_enabled():
            await host._embedding_queue.put(dict(summary))
            return
        await self._maybe_upsert_summary_embedding(summary)

    async def _run_embedding_worker(self) -> None:
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        if host._embedding_queue is None:
            return
        while True:
            item = await host._embedding_queue.get()
            if item is None:
                host._embedding_queue.task_done()
                break
            batch = [item]
            should_stop = False
            batch_size = max(1, int(host._embedding_batch_size))
            deadline = time.monotonic() + max(0.0, float(host._embedding_batch_wait_seconds))
            while len(batch) < batch_size:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                try:
                    next_item = await asyncio.wait_for(host._embedding_queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if next_item is None:
                    host._embedding_queue.task_done()
                    should_stop = True
                    break
                batch.append(next_item)
            host._embedding_active_count += len(batch)
            try:
                await self._maybe_upsert_summary_embeddings(batch)
            finally:
                host._embedding_active_count = max(
                    0,
                    host._embedding_active_count - len(batch),
                )
                for _ in batch:
                    host._embedding_queue.task_done()
            if should_stop:
                break


__all__ = ["L3SummaryEmbeddingMixin"]
