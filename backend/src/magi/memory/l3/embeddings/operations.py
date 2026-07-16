"""Embedding operations for L3 summary storage."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.embedding_pipeline import (
    EmbeddingPipelineItem,
    EmbeddingPipelineResult,
    partition_embedding_pipeline_items,
    verify_active_rebuild_profile,
)
from ...embedding.embedding_service import EmbeddingResult, MemoryEmbeddingService
from ...embedding.sqlite_vec_index import SqliteVecIndex
from ...operation_barrier import optional_operation_guard
from ..retrieval.search import ranked_vector_summaries
from ..storage.schema import (
    EMBEDDING_STATUS_DISABLED,
    EMBEDDING_STATUS_READY,
    SUMMARY_CHUNKS_TABLE,
)
from ..storage.serialization import row_to_summary_dict
from .summaries import (
    EMBEDDING_TEXT_BUILDER_VERSION,
    build_embedding_pipeline,
    build_summary_embedding_chunks,
    chunk_id_for_summary,
    fetch_summary_chunk_rows_by_ids,
    fold_summary_chunk_hits,
    get_embedding_text,
    profile_from_embedding_result,
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
    _operation_guard_factory: Callable[[], Any] | None

    async def initialize(self) -> None: ...

    def embedding_mutation_guard(self) -> Any: ...

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

        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute("SELECT COALESCE(MAX(rowid), 0) FROM summaries") as cursor:
                row = await cursor.fetchone()
        high_water_rowid = int(row[0] or 0) if row is not None else 0

        processed = 0
        last_rowid = 0
        async with host._vector_index.rebuild_session():
            while last_rowid < high_water_rowid:
                async with sqlite_connection_async(host.db_path) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        """
                        SELECT rowid AS rebuild_rowid, *
                        FROM summaries
                        WHERE rowid > ? AND rowid <= ?
                          AND derivation_state = 'current'
                        ORDER BY rowid ASC
                        LIMIT ?
                        """,
                        (last_rowid, high_water_rowid, normalized_batch_size),
                    ) as cursor:
                        rows = await cursor.fetchall()
                if not rows:
                    break
                last_rowid = int(rows[-1]["rebuild_rowid"])
                summaries = [host._row_to_dict(row) for row in rows]
                await self._maybe_upsert_summary_embeddings(summaries)
                processed += len(summaries)
                if progress_callback is not None:
                    await progress_callback(processed)
            await host._vector_index.prune_orphans(
                valid_entity_query=f"""
                    SELECT chunks.chunk_id AS entity_id
                    FROM {SUMMARY_CHUNKS_TABLE} AS chunks
                    JOIN summaries ON summaries.summary_id = chunks.summary_id
                    WHERE summaries.derivation_state = 'current'
                """,
                mutation_guard_factory=host.embedding_mutation_guard,
            )
            verify_active_rebuild_profile(
                embedding_service=host._embedding_service,
                vector_index=host._vector_index,
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
            )
        return processed

    async def _maybe_upsert_summary_embedding(self, summary: Dict[str, Any]) -> None:
        await self._maybe_upsert_summary_embeddings([summary])

    async def _maybe_upsert_summary_embeddings(self, summaries: List[Dict[str, Any]]) -> None:
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        if not host._vectors_enabled():
            return
        summary_ids = list(
            dict.fromkeys(
                str(summary.get("summary_id") or "").strip()
                for summary in summaries
                if str(summary.get("summary_id") or "").strip()
            )
        )
        current_summaries = await host.fetch_by_ids(summary_ids)
        if not current_summaries:
            return
        pipeline_items = [
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
            for summary in current_summaries
        ]
        embeddable_items, unembeddable_items = partition_embedding_pipeline_items(pipeline_items)
        await self._remove_unembeddable_summary_embeddings(unembeddable_items)

        pipeline = build_embedding_pipeline(
            embedding_service=host._embedding_service,
            vector_index=host._vector_index,
        )
        if pipeline is None or not embeddable_items:
            return
        prepared_results = await pipeline.prepare_items(embeddable_items)
        if not prepared_results:
            return
        async with optional_operation_guard(host._operation_guard_factory):
            async with host.embedding_mutation_guard():
                publishable_results = await self._current_prepared_embedding_results(
                    prepared_results
                )
                results = await pipeline.persist_results(publishable_results)
                if not results:
                    return
                (
                    stale_embeddings,
                    obsolete_chunk_ids,
                ) = await self._publish_summary_embedding_results(results)
                for chunk_id, embedding in stale_embeddings:
                    try:
                        if host._vector_index is not None:
                            await host._vector_index.delete_embedding(
                                entity_id=chunk_id,
                                embedding=embedding,
                            )
                    except Exception as exc:
                        logger.warning(
                            "Failed to remove stale summary embedding chunk %s: %s",
                            chunk_id,
                            exc,
                        )
                for chunk_id in obsolete_chunk_ids:
                    try:
                        if host._vector_index is not None:
                            await host._vector_index.delete_entity(entity_id=chunk_id)
                    except Exception as exc:
                        logger.warning(
                            "Failed to remove obsolete summary embedding chunk %s: %s",
                            chunk_id,
                            exc,
                        )

    async def _remove_unembeddable_summary_embeddings(
        self,
        items: list[EmbeddingPipelineItem],
    ) -> None:
        """Remove published chunks only for current summaries with no canonical text."""
        if not items:
            return
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        snapshots = {
            item.parent_id: dict(item.payload)
            for item in items
            if isinstance(item.payload, Mapping)
        }
        if not snapshots:
            return

        detached_chunk_ids: list[str] = []
        async with optional_operation_guard(host._operation_guard_factory):
            async with host.embedding_mutation_guard():
                async with sqlite_connection_async(host.db_path) as db:
                    db.row_factory = aiosqlite.Row
                    await db.execute("BEGIN IMMEDIATE")
                    try:
                        for summary_id, snapshot in snapshots.items():
                            async with db.execute(
                                "SELECT * FROM summaries WHERE summary_id = ?",
                                (summary_id,),
                            ) as cursor:
                                current = await cursor.fetchone()
                            if not _embedded_parent_is_current(current, snapshot):
                                continue
                            current_summary = host._row_to_dict(current)
                            if build_summary_embedding_chunks(current_summary):
                                continue
                            detached_chunk_ids.extend(
                                await self._detach_summary_embedding_on_connection(
                                    db,
                                    summary_id=summary_id,
                                )
                            )
                        await db.commit()
                    except BaseException:
                        await db.rollback()
                        raise
                await self._delete_summary_vectors_unlocked(detached_chunk_ids)

    async def _current_prepared_embedding_results(
        self,
        results: list[EmbeddingPipelineResult],
    ) -> list[EmbeddingPipelineResult]:
        """Drop results whose parent changed while the external model was running."""
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        current_summaries = await host.fetch_by_ids(
            list(dict.fromkeys(result.parent_id for result in results))
        )
        current_by_id = {
            str(summary.get("summary_id") or ""): summary for summary in current_summaries
        }
        return [
            result
            for result in results
            if _embedded_parent_is_current(
                current_by_id.get(result.parent_id),
                result.payload,
            )
        ]

    async def _publish_summary_embedding_results(
        self,
        results: list[EmbeddingPipelineResult],
    ) -> tuple[list[tuple[str, EmbeddingResult]], list[str]]:
        """Publish metadata only if the embedded parent version is still current."""
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        stale_embeddings: list[tuple[str, EmbeddingResult]] = []
        obsolete_chunk_ids: list[str] = []
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                for result in results:
                    summary = result.payload
                    async with db.execute(
                        """
                        SELECT *
                        FROM summaries
                        WHERE summary_id = ?
                        """,
                        (result.parent_id,),
                    ) as cursor:
                        current = await cursor.fetchone()
                    new_chunk_ids = [
                        chunk_id_for_summary(result.parent_id, chunk.chunk_index)
                        for chunk in result.chunks
                    ]
                    if not _embedded_parent_is_current(current, summary):
                        stale_embeddings.extend(zip(new_chunk_ids, result.embeddings, strict=True))
                        continue

                    async with db.execute(
                        f"SELECT chunk_id FROM {SUMMARY_CHUNKS_TABLE} WHERE summary_id = ?",
                        (result.parent_id,),
                    ) as cursor:
                        previous_rows = await cursor.fetchall()
                    previous_chunk_ids = [str(row["chunk_id"]) for row in previous_rows]
                    await db.execute(
                        f"DELETE FROM {SUMMARY_CHUNKS_TABLE} WHERE summary_id = ?",
                        (result.parent_id,),
                    )
                    await db.executemany(
                        f"""
                        INSERT INTO {SUMMARY_CHUNKS_TABLE}(
                            chunk_id, summary_id, chunk_index, chunk_text,
                            char_start, char_end, token_estimate, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                chunk_id_for_summary(result.parent_id, chunk.chunk_index),
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
                    profile = profile_from_embedding_result(
                        embedding_service=host._embedding_service,
                        result=result.embeddings[0],
                    )
                    await db.execute(
                        """
                        UPDATE summaries
                        SET embedding_status = ?, embedding_profile_id = ?,
                            embedding_chunk_count = ?, last_embedded_at = ?
                        WHERE summary_id = ?
                        """,
                        (
                            EMBEDDING_STATUS_READY,
                            profile.profile_id,
                            len(result.chunks),
                            result.embedded_at,
                            result.parent_id,
                        ),
                    )
                    new_chunk_id_set = set(new_chunk_ids)
                    obsolete_chunk_ids.extend(
                        chunk_id
                        for chunk_id in previous_chunk_ids
                        if chunk_id not in new_chunk_id_set
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return stale_embeddings, list(dict.fromkeys(obsolete_chunk_ids))

    async def _detach_summary_embedding_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        summary_id: str,
    ) -> list[str]:
        """Detach chunk metadata inside a caller-owned correction transaction."""
        async with db.execute(
            f"SELECT chunk_id FROM {SUMMARY_CHUNKS_TABLE} WHERE summary_id = ?",
            (summary_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        chunk_ids = [str(row[0]) for row in rows]
        await db.execute(
            f"DELETE FROM {SUMMARY_CHUNKS_TABLE} WHERE summary_id = ?",
            (summary_id,),
        )
        await db.execute(
            """
            UPDATE summaries
            SET embedding_status = ?, embedding_profile_id = NULL,
                embedding_chunk_count = 0, last_embedded_at = NULL
            WHERE summary_id = ?
            """,
            (EMBEDDING_STATUS_DISABLED, summary_id),
        )
        return chunk_ids

    async def _delete_summary_vectors_unlocked(self, chunk_ids: List[str]) -> None:
        """Delete vector rows while the caller holds the embedding mutation guard."""
        host = cast(_L3SummaryEmbeddingHostProtocol, self)
        if host._vector_index is None:
            return
        for chunk_id in dict.fromkeys(chunk_ids):
            await host._vector_index.delete_entity(entity_id=chunk_id)

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


def _embedded_parent_is_current(
    current: Mapping[str, Any] | aiosqlite.Row | None,
    embedded_summary: Dict[str, Any],
) -> bool:
    if current is None or str(current["derivation_state"]) != "current":
        return False
    current_summary = (
        row_to_summary_dict(current) if isinstance(current, aiosqlite.Row) else dict(current)
    )
    return get_embedding_text(current_summary) == get_embedding_text(embedded_summary) and int(
        current_summary.get("source_revision") or 0
    ) == int(embedded_summary.get("source_revision") or 0)


__all__ = ["L3SummaryEmbeddingMixin"]
