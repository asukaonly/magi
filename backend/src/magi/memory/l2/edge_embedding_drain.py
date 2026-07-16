"""Dedicated drain that embeds pending L2 knowledge-graph edges (#86)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

import aiosqlite

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
_MAX_SQL_IN_PARAMS = 900


@dataclass(frozen=True, slots=True)
class _EdgeEmbeddingSnapshot:
    triple_id: str
    subject_id: str
    predicate: str
    object_id: str
    evidence_text: str | None
    natural_summary: str | None
    subject_name: str | None
    object_name: str | None
    text: str
    status: str
    updated_at: float
    embedding_status: str
    embedding_profile_id: str | None
    last_embedded_at: float | None


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

        try:
            return await self.embed_rows_if_current(rows)
        except Exception as exc:
            logger.warning("Failed to embed pending edges: %s", exc)
            return 0

    async def embed_rows_if_current(self, rows: list[Any]) -> int:
        """Embed source rows that still match their canonical database state."""

        items = self._build_pipeline_items(rows)
        if not items:
            return 0

        return await self._upsert_pending_edges(items)

    async def _fetch_pending_edges(self, *, batch_limit: int) -> list[Any]:
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT kg.triple_id, kg.subject_id, kg.predicate, kg.object_id, "
                "kg.evidence_text, kg.natural_summary, "
                "kg.status, kg.updated_at, kg.embedding_status, "
                "kg.embedding_profile_id, kg.last_embedded_at, "
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
            snapshot = self._snapshot_for_row(row)
            if not snapshot.text.strip():
                continue
            items.append(
                EmbeddingPipelineItem(
                    parent_id=snapshot.triple_id,
                    chunks=[
                        ChunkedText(
                            chunk_id=snapshot.triple_id,
                            text=snapshot.text,
                            chunk_index=0,
                            char_start=0,
                            char_end=len(snapshot.text),
                            token_estimate=max(1, len(snapshot.text) // 4),
                        )
                    ],
                    metadata={"kind": "edge"},
                    payload=snapshot,
                )
            )
        return items

    @staticmethod
    def _snapshot_for_row(row: Any) -> _EdgeEmbeddingSnapshot:
        subject_id = str(row["subject_id"])
        predicate = str(row["predicate"])
        object_id = str(row["object_id"])
        evidence_text = row["evidence_text"]
        natural_summary = row["natural_summary"]
        subject_name = row["subject_name"]
        object_name = row["object_name"]
        text = build_l2_edge_embedding_text(
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            evidence_text=evidence_text,
            natural_summary=natural_summary,
            subject_name=subject_name,
            object_name=object_name,
        )
        return _EdgeEmbeddingSnapshot(
            triple_id=str(row["triple_id"]),
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            evidence_text=(str(evidence_text) if evidence_text is not None else None),
            natural_summary=(str(natural_summary) if natural_summary is not None else None),
            subject_name=(str(subject_name) if subject_name is not None else None),
            object_name=(str(object_name) if object_name is not None else None),
            text=str(text),
            status=str(row["status"]),
            updated_at=float(row["updated_at"]),
            embedding_status=str(row["embedding_status"] or "pending"),
            embedding_profile_id=(
                str(row["embedding_profile_id"])
                if row["embedding_profile_id"] is not None
                else None
            ),
            last_embedded_at=(
                float(row["last_embedded_at"]) if row["last_embedded_at"] is not None else None
            ),
        )

    async def _upsert_pending_edges(self, items: list[EmbeddingPipelineItem]) -> int:
        pipeline = MemoryEmbeddingPipeline(
            embedding_service=self._embedding_service,
            vector_index=self._edge_vector_index,
            text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
        )

        results = await pipeline.prepare_items(items)
        if not results:
            return 0
        async with self._vector_source_write_lock():
            current = await self._load_edge_snapshots([str(result.parent_id) for result in results])
            current_results = [
                result
                for result in results
                if isinstance(result.payload, _EdgeEmbeddingSnapshot)
                and current.get(result.parent_id) == result.payload
            ]
            if not current_results:
                return 0
            persisted = await pipeline.persist_results(current_results)
            state_updates = self._edge_embedding_state_updates(persisted)
            if not state_updates:
                return 0
            updated_ids = await self._mark_edges_embedded(state_updates)
            for result in persisted:
                if result.parent_id in updated_ids:
                    continue
                await self._edge_vector_index.delete_embedding(
                    entity_id=result.parent_id,
                    embedding=result.embeddings[0],
                )
            return len(updated_ids)

    def _edge_embedding_state_updates(
        self,
        results: list[Any],
    ) -> list[tuple[_EdgeEmbeddingSnapshot, str | None, float | None]]:
        state_updates: list[tuple[_EdgeEmbeddingSnapshot, str | None, float | None]] = []
        for result in results:
            if not isinstance(result.payload, _EdgeEmbeddingSnapshot):
                continue
            profile = self._embedding_service.profile_from_result(
                result.embeddings[0],
                text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
            )
            state_updates.append((result.payload, profile.profile_id, result.embedded_at))
        return state_updates

    async def _mark_edges_embedded(
        self,
        state_updates: list[tuple[_EdgeEmbeddingSnapshot, str | None, float | None]],
    ) -> set[str]:
        updated_ids: set[str] = set()
        async with sqlite_connection_async(self._db_path) as db:
            for snapshot, profile_id, embedded_at in state_updates:
                cursor = await db.execute(
                    """
                    UPDATE knowledge_graph
                    SET embedding_status = 'ready', embedding_profile_id = ?, last_embedded_at = ?
                    WHERE triple_id = ?
                      AND subject_id = ?
                      AND predicate = ?
                      AND object_id = ?
                      AND evidence_text IS ?
                      AND natural_summary IS ?
                      AND status = ?
                      AND updated_at = ?
                      AND COALESCE(embedding_status, 'pending') = ?
                      AND embedding_profile_id IS ?
                      AND last_embedded_at IS ?
                      AND (SELECT canonical_name FROM entity_catalog WHERE entity_id = subject_id)
                          IS ?
                      AND (SELECT canonical_name FROM entity_catalog WHERE entity_id = object_id)
                          IS ?
                    """,
                    (
                        profile_id,
                        embedded_at,
                        snapshot.triple_id,
                        snapshot.subject_id,
                        snapshot.predicate,
                        snapshot.object_id,
                        snapshot.evidence_text,
                        snapshot.natural_summary,
                        snapshot.status,
                        snapshot.updated_at,
                        snapshot.embedding_status,
                        snapshot.embedding_profile_id,
                        snapshot.last_embedded_at,
                        snapshot.subject_name,
                        snapshot.object_name,
                    ),
                )
                if int(cursor.rowcount) == 1:
                    updated_ids.add(snapshot.triple_id)
            await db.commit()
        return updated_ids

    async def _load_edge_snapshots(
        self,
        triple_ids: list[str],
    ) -> dict[str, _EdgeEmbeddingSnapshot]:
        if not triple_ids:
            return {}
        rows: list[aiosqlite.Row] = []
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            for start in range(0, len(triple_ids), _MAX_SQL_IN_PARAMS):
                chunk = triple_ids[start : start + _MAX_SQL_IN_PARAMS]
                placeholders = ", ".join("?" for _ in chunk)
                async with db.execute(
                    f"""
                    SELECT kg.triple_id, kg.subject_id, kg.predicate, kg.object_id,
                           kg.evidence_text, kg.natural_summary, kg.status, kg.updated_at,
                           kg.embedding_status, kg.embedding_profile_id, kg.last_embedded_at,
                           sc.canonical_name AS subject_name,
                           oc.canonical_name AS object_name
                    FROM knowledge_graph AS kg
                    LEFT JOIN entity_catalog AS sc ON sc.entity_id = kg.subject_id
                    LEFT JOIN entity_catalog AS oc ON oc.entity_id = kg.object_id
                    WHERE kg.triple_id IN ({placeholders})
                    """,
                    tuple(chunk),
                ) as cursor:
                    rows.extend(await cursor.fetchall())
        snapshots = [self._snapshot_for_row(row) for row in rows]
        return {snapshot.triple_id: snapshot for snapshot in snapshots}

    def _vector_source_write_lock(self) -> asyncio.Lock:
        coordinator = getattr(self._edge_vector_index, "_coordinator", None)
        if coordinator is not None:
            return coordinator.source_write_lock
        lock = getattr(self._edge_vector_index, "_magi_source_embedding_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(self._edge_vector_index, "_magi_source_embedding_lock", lock)
        return lock


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
