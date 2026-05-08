"""Knowledge-graph edge embedding helpers for L2 entity maintenance."""

from __future__ import annotations

from typing import Any, Protocol

import aiosqlite

from .....core.logger import get_logger
from .....core.sqlite import sqlite_connection_async
from ....embedding.chunking import ChunkedText
from ....embedding.embedding_pipeline import EmbeddingPipelineItem
from ....embedding.embedding_text_builders import (
    L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
    build_l2_edge_embedding_text,
)

logger = get_logger("magi.memory.l2.entities.maintenance")


class _EmbeddingMaintenanceStatsProtocol(Protocol):
    edge_embeddings_cleaned: int
    edges_embedded: int
    errors: list[str]


class _EmbeddingMaintenanceHostProtocol(Protocol):
    _db_path: str
    _embedding_service: Any | None
    _edge_vector_index: Any | None


class L2EntityEmbeddingMaintenanceMixin:
    """Maintain vector embeddings for active L2 knowledge-graph edges."""

    async def _clean_non_active_edge_embeddings(
        self,
        stats: _EmbeddingMaintenanceStatsProtocol,
    ) -> None:
        """Remove vector embeddings for edges that are no longer 'active'."""
        host = self._embedding_maintenance_host()
        if host._edge_vector_index is None:
            return
        async with sqlite_connection_async(host._db_path) as db:
            async with db.execute("""
                SELECT triple_id FROM knowledge_graph
                WHERE status != 'active' AND embedding_status = 'ready'
                LIMIT 500
                """) as cur:
                rows = await cur.fetchall()
        if not rows:
            return
        for row in rows:
            triple_id = str(row[0])
            try:
                await host._edge_vector_index.delete_entity(entity_id=triple_id)
            except Exception:
                pass
        triple_ids = [str(r[0]) for r in rows]
        placeholders = ", ".join("?" for _ in triple_ids)
        async with sqlite_connection_async(host._db_path) as db:
            await db.execute(
                f"UPDATE knowledge_graph SET embedding_status = 'disabled' WHERE triple_id IN ({placeholders})",
                tuple(triple_ids),
            )
            await db.commit()
        stats.edge_embeddings_cleaned = len(triple_ids)

    async def _embed_pending_edges(
        self,
        stats: _EmbeddingMaintenanceStatsProtocol,
        *,
        batch_limit: int = 200,
    ) -> None:
        """Embed knowledge_graph edges that have embedding_status='pending'."""
        host = self._embedding_maintenance_host()
        if host._embedding_service is None or host._edge_vector_index is None:
            return

        from . import MemoryEmbeddingPipeline

        pipeline = MemoryEmbeddingPipeline(
            embedding_service=host._embedding_service,
            vector_index=host._edge_vector_index,
            text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
        )

        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
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
                rows = await cur.fetchall()

        if not rows:
            return

        items: list[EmbeddingPipelineItem] = []
        for row in rows:
            text = build_l2_edge_embedding_text(
                subject_id=str(row["subject_id"]),
                predicate=str(row["predicate"]),
                object_id=str(row["object_id"]),
                evidence_text=row["evidence_text"],
                natural_summary=row["natural_summary"],
                subject_name=row["subject_name"],
                object_name=row["object_name"],
            )
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

        if not items:
            return

        try:
            results = await pipeline.upsert_items(items)
            state_updates: list[tuple[str, str | None, float | None]] = []
            for result in results:
                profile = host._embedding_service.profile_from_result(
                    result.embeddings[0],
                    text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
                )
                state_updates.append((result.parent_id, profile.profile_id, result.embedded_at))
            if state_updates:
                async with sqlite_connection_async(host._db_path) as db:
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
                stats.edges_embedded = len(state_updates)
        except Exception as exc:
            logger.warning("Failed to embed pending edges: %s", exc)
            stats.errors.append(f"edge_embedding: {exc}")

    def _embedding_maintenance_host(self) -> _EmbeddingMaintenanceHostProtocol:
        return self  # type: ignore[return-value]
