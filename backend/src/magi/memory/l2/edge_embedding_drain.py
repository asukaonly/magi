"""Dedicated drain that embeds pending L2 knowledge-graph edges (#86)."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from ..embedding.chunking import ChunkedText
from ..embedding.embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from ..embedding.embedding_text_builders import (
    L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
    build_l2_edge_embedding_text,
)
from ..operation_barrier import optional_operation_guard

logger = get_logger(__name__)


class EdgeEmbeddingDrainer:
    """Embed knowledge_graph edges with embedding_status='pending'. Never raises."""

    def __init__(
        self,
        *,
        db_path: str,
        embedding_service: Any,
        edge_vector_index: Any,
    ) -> None:
        self._db_path = db_path
        self._embedding_service = embedding_service
        self._edge_vector_index = edge_vector_index

    async def drain_once(self, *, batch_limit: int = 200) -> int:
        """Embed one batch of pending edges. Returns the number of edges embedded."""
        if self._embedding_service is None or self._edge_vector_index is None:
            return 0

        rows = await self._fetch_pending_edges(batch_limit=batch_limit)
        if not rows:
            return 0

        items = self._build_pipeline_items(rows)
        if not items:
            return 0

        return await self._upsert_pending_edges(items)

    async def _fetch_pending_edges(self, *, batch_limit: int) -> list[Any]:
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                "SELECT kg.triple_id, kg.subject_id, kg.predicate, kg.object_id, "
                "kg.evidence_text, kg.natural_summary, "
                "sc.canonical_name AS subject_name, oc.canonical_name AS object_name "
                "FROM knowledge_graph kg "
                "LEFT JOIN entity_catalog sc ON sc.entity_id = kg.subject_id "
                "LEFT JOIN entity_catalog oc ON oc.entity_id = kg.object_id "
                "WHERE kg.embedding_status = 'pending' AND kg.status = 'active' "
                "ORDER BY kg.updated_at DESC LIMIT ?",
                (batch_limit,),
            ) as cur:
                return await cur.fetchall()

    def _build_pipeline_items(self, rows: list[Any]) -> list[EmbeddingPipelineItem]:
        items: list[EmbeddingPipelineItem] = []
        for row in rows:
            text = self._embedding_text_for_row(row)
            if not text.strip():
                continue
            triple_id = str(row["triple_id"])
            items.append(
                EmbeddingPipelineItem(
                    parent_id=triple_id,
                    chunks=[
                        ChunkedText(
                            chunk_id=triple_id,
                            text=text,
                            chunk_index=0,
                            char_start=0,
                            char_end=len(text),
                            token_estimate=max(1, len(text) // 4),
                        )
                    ],
                    metadata={"kind": "edge"},
                )
            )
        return items

    @staticmethod
    def _embedding_text_for_row(row: Any) -> str:
        return build_l2_edge_embedding_text(
            subject_id=str(row["subject_id"]),
            predicate=str(row["predicate"]),
            object_id=str(row["object_id"]),
            evidence_text=row["evidence_text"],
            natural_summary=row["natural_summary"],
            subject_name=row["subject_name"],
            object_name=row["object_name"],
        )

    async def _upsert_pending_edges(self, items: list[EmbeddingPipelineItem]) -> int:
        pipeline = MemoryEmbeddingPipeline(
            embedding_service=self._embedding_service,
            vector_index=self._edge_vector_index,
            text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
        )

        embedded_count = 0
        try:
            results = await pipeline.upsert_items(items)
            state_updates = self._edge_embedding_state_updates(results)
            if state_updates:
                await self._mark_edges_embedded(state_updates)
            embedded_count = len(state_updates)
        except Exception as exc:
            logger.warning("Failed to embed pending edges: %s", exc)

        return embedded_count

    def _edge_embedding_state_updates(
        self,
        results: list[Any],
    ) -> list[tuple[str, str | None, float | None]]:
        state_updates: list[tuple[str, str | None, float | None]] = []
        for result in results:
            profile = self._embedding_service.profile_from_result(
                result.embeddings[0],
                text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
            )
            state_updates.append((result.parent_id, profile.profile_id, result.embedded_at))
        return state_updates

    async def _mark_edges_embedded(
        self,
        state_updates: list[tuple[str, str | None, float | None]],
    ) -> None:
        async with sqlite_connection_async(self._db_path) as db:
            await db.executemany(
                """
                UPDATE knowledge_graph
                SET embedding_status = 'ready', embedding_profile_id = ?, last_embedded_at = ?
                WHERE triple_id = ?
                """,
                [
                    (profile_id, embedded_at, triple_id)
                    for triple_id, profile_id, embedded_at in state_updates
                ],
            )
            await db.commit()


class L2EdgeEmbeddingWorker:
    """Owns a background loop that drains pending edge embeddings (#86)."""

    def __init__(
        self,
        *,
        drainer: EdgeEmbeddingDrainer,
        idle_interval_seconds: float = 5.0,
        batch_limit: int = 200,
    ) -> None:
        self._drainer = drainer
        self._idle_interval = max(0.01, float(idle_interval_seconds))
        self._batch_limit = int(batch_limit)
        self._running = False
        self._task: asyncio.Task | None = None
        self._operation_guard_factory: Callable[[], Any] | None = None

    def set_operation_guard_factory(self, factory: Callable[[], Any]) -> None:
        """Bind the unified clear barrier used by each drain batch."""
        self._operation_guard_factory = factory

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        backoff = self._idle_interval
        while self._running:
            try:
                async with optional_operation_guard(self._operation_guard_factory):
                    n = await self._drainer.drain_once(batch_limit=self._batch_limit)
                backoff = self._idle_interval
                if n >= self._batch_limit:
                    continue  # likely more pending — drain again immediately
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # defensive; drain_once is already never-raise
                logger.warning("edge embedding drain loop error: %s", exc)
                backoff = min(backoff * 6, 300.0)
            await asyncio.sleep(backoff)
