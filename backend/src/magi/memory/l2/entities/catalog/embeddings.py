"""Embedding and vector-search helpers for the L2 entity catalog."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Protocol, cast

import aiosqlite

from .....config.models import EmbeddingBackend
from .....core.sqlite import sqlite_connection_async
from ....embedding.chunking import ChunkedText
from ....embedding.embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from ....embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ....embedding.embedding_text_builders import build_l2_entity_embedding_text
from ....embedding.sqlite_vec_index import SqliteVecIndex

logger = logging.getLogger("magi.memory.l2.entities.catalog")

EMBEDDING_TEXT_BUILDER_VERSION = "l2_entity_v1"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_DISABLED = "disabled"


class _EntityCatalogEmbeddingHostProtocol(Protocol):
    db_path: str
    _embedding_service: MemoryEmbeddingService | None
    _memory_config_getter: Callable[[], Any] | None
    _default_vector_enabled: bool
    _vector_index: SqliteVecIndex | None

    async def initialize(self) -> None: ...

    async def _list_entities(
        self,
        *,
        limit: int,
        offset: int = 0,
        entity_type: Optional[str] = None,
        entity_ids: list[str] | None = None,
        order_by_recency: bool = False,
    ) -> list[dict[str, Any]]: ...


class L2EntityCatalogEmbeddingMixin:
    """Embedding maintenance and semantic search behavior for entity catalogs."""

    async def rebuild_embeddings(self, *, batch_size: int = 100) -> int:
        """Rebuild all L2 entity vectors from canonical catalog rows."""
        host = self._embedding_host()
        await host.initialize()
        normalized_batch_size = max(1, int(batch_size))
        if (
            not self._vectors_enabled()
            or host._embedding_service is None
            or host._vector_index is None
        ):
            return 0

        await host._vector_index.clear()
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute(
                """
                UPDATE entity_catalog
                SET embedding_status = ?, embedding_profile_id = NULL, last_embedded_at = NULL
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
                    SELECT entity_id
                    FROM entity_catalog
                    ORDER BY updated_at DESC, entity_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (normalized_batch_size, offset),
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                break
            entity_ids = [str(row["entity_id"]) for row in rows]
            for entity_id in entity_ids:
                await self._maybe_embed_entity(entity_id)
            processed += len(entity_ids)
            offset += len(rows)
        return processed

    def _vectors_enabled(self) -> bool:
        host = self._embedding_host()
        if host._embedding_service is None:
            return False
        config = self._current_memory_config()
        if config is None:
            return host._default_vector_enabled
        return bool(
            config.embedding.backend == EmbeddingBackend.SQLITE_VEC
            and config.l2.enabled
            and config.l2.vectors_enabled
        )

    def _current_memory_config(self) -> Any:
        host = self._embedding_host()
        if host._memory_config_getter is None:
            return None
        try:
            return host._memory_config_getter()
        except Exception:
            return None

    async def _maybe_embed_entity(self, entity_id: str) -> None:
        if not self._vectors_enabled():
            return
        pipeline = self._build_embedding_pipeline()
        if pipeline is None:
            return
        try:
            text = await self._build_entity_embedding_text(entity_id)
            if not text:
                return
            results = await pipeline.upsert_items(
                [
                    EmbeddingPipelineItem(
                        parent_id=entity_id,
                        chunks=[
                            ChunkedText(
                                chunk_id=entity_id,
                                text=text,
                                chunk_index=0,
                                char_start=0,
                                char_end=len(text),
                                token_estimate=max(1, len(text) // 4),
                            )
                        ],
                        metadata={"kind": "entity"},
                    )
                ]
            )
            if not results:
                return
            profile = self._profile_from_embedding_result(results[0].embeddings[0])
            await self._update_entity_embedding_state(
                entity_id=entity_id,
                status=EMBEDDING_STATUS_READY,
                profile_id=profile.profile_id,
                embedded_at=results[0].embedded_at,
            )
        except Exception as exc:
            logger.debug("Failed to embed L2 entity %s: %s", entity_id, exc)

    def _build_embedding_pipeline(self) -> MemoryEmbeddingPipeline | None:
        host = self._embedding_host()
        if host._embedding_service is None or host._vector_index is None:
            return None
        return MemoryEmbeddingPipeline(
            embedding_service=host._embedding_service,
            vector_index=host._vector_index,
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )

    async def _build_entity_embedding_text(self, entity_id: str) -> str:
        host = self._embedding_host()
        entities = await host._list_entities(limit=1, entity_ids=[entity_id])
        if not entities:
            return ""
        entity = entities[0]
        text = build_l2_entity_embedding_text(
            canonical_name=str(entity.get("canonical_name") or ""),
            entity_type=str(entity.get("entity_type") or ""),
            aliases=[str(alias) for alias in entity.get("aliases", [])],
        )
        return str(text)

    def _profile_from_embedding_result(self, result: Any) -> EmbeddingProfile:
        host = self._embedding_host()
        getter = getattr(host._embedding_service, "profile_from_result", None)
        if callable(getter):
            profile = getter(result, text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION)
            return cast(EmbeddingProfile, profile)
        return EmbeddingProfile.build(
            provider_name="unknown",
            model_name=result.model_name,
            dimension=result.dimension,
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )

    async def _update_entity_embedding_state(
        self,
        *,
        entity_id: str,
        status: str,
        profile_id: str | None,
        embedded_at: float | None,
    ) -> None:
        host = self._embedding_host()
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute(
                """
                UPDATE entity_catalog
                SET embedding_status = ?, embedding_profile_id = ?, last_embedded_at = ?, updated_at = updated_at
                WHERE entity_id = ?
                """,
                (status, profile_id, embedded_at, entity_id),
            )
            await db.commit()

    async def search_entities_semantic(
        self,
        query_text: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search entities using vector similarity. Returns [] if vectors are disabled."""
        host = self._embedding_host()
        if (
            not self._vectors_enabled()
            or host._embedding_service is None
            or host._vector_index is None
        ):
            return []
        query_text = query_text.strip()
        if not query_text:
            return []
        try:
            embedding = await host._embedding_service.embed_text(query_text)
            if embedding is None:
                return []
            embedding = host._embedding_service.result_for_index(
                embedding,
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
            )
            hits = await host._vector_index.search(embedding=embedding, limit=limit)
        except Exception as exc:
            logger.debug("L2 entity semantic search failed: %s", exc)
            return []
        if not hits:
            return []

        hit_ids = [hit.entity_id for hit in hits]
        distance_by_id = {hit.entity_id: hit.distance for hit in hits}
        entities = await host._list_entities(limit=len(hit_ids), entity_ids=hit_ids)
        for entity in entities:
            entity["distance"] = distance_by_id.get(entity["entity_id"])
        entities.sort(key=lambda item: item.get("distance") or float("inf"))
        return entities[:limit]

    def _embedding_host(self) -> _EntityCatalogEmbeddingHostProtocol:
        return cast(_EntityCatalogEmbeddingHostProtocol, self)


__all__ = [
    "EMBEDDING_STATUS_DISABLED",
    "EMBEDDING_STATUS_READY",
    "EMBEDDING_TEXT_BUILDER_VERSION",
    "L2EntityCatalogEmbeddingMixin",
]
