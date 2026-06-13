"""Dedicated drain that embeds pending L2 knowledge-graph edges (#86)."""

from __future__ import annotations

from typing import Any

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from ..embedding.chunking import ChunkedText
from ..embedding.embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from ..embedding.embedding_text_builders import (
    L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
    build_l2_edge_embedding_text,
)

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

        pipeline = MemoryEmbeddingPipeline(
            embedding_service=self._embedding_service,
            vector_index=self._edge_vector_index,
            text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
        )

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
                rows = await cur.fetchall()

        if not rows:
            return 0

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
            return 0

        embedded_count = 0
        try:
            results = await pipeline.upsert_items(items)
            state_updates: list[tuple[str, str | None, float | None]] = []
            for result in results:
                profile = self._embedding_service.profile_from_result(
                    result.embeddings[0],
                    text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
                )
                state_updates.append((result.parent_id, profile.profile_id, result.embedded_at))
            if state_updates:
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
            embedded_count = len(state_updates)
        except Exception as exc:
            logger.warning("Failed to embed pending edges: %s", exc)

        return embedded_count
