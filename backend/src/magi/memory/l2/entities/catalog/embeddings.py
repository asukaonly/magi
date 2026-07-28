"""Embedding and vector-search helpers for the L2 entity catalog."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Protocol, cast

import aiosqlite

from .....config.models import EmbeddingBackend
from .....core.sqlite import sqlite_connection_async
from ....embedding.chunking import ChunkedText
from ....embedding.embedding_pipeline import (
    EmbeddingPipelineItem,
    MemoryEmbeddingPipeline,
    verify_active_rebuild_profile,
)
from ....embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ....embedding.embedding_text_builders import build_l2_entity_embedding_text
from ....embedding.sqlite_vec_index import SqliteVecIndex

logger = logging.getLogger("magi.memory.l2.entities.catalog")

EMBEDDING_TEXT_BUILDER_VERSION = "l2_entity_v1"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class _EntityEmbeddingSnapshot:
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: tuple[str, ...]
    text: str
    updated_at: float
    embedding_status: str
    embedding_profile_id: str | None
    last_embedded_at: float | None


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

    async def rebuild_embeddings(
        self,
        *,
        batch_size: int = 100,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> int:
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

        processed = 0
        last_rowid = 0
        async with host._vector_index.rebuild_session():
            async with sqlite_connection_async(host.db_path) as db:
                async with db.execute(
                    "SELECT COALESCE(MAX(rowid), 0) FROM entity_catalog"
                ) as cursor:
                    high_water_row = await cursor.fetchone()
            high_water_rowid = int(high_water_row[0] or 0) if high_water_row else 0
            while last_rowid < high_water_rowid:
                async with sqlite_connection_async(host.db_path) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        """
                        SELECT rowid AS rebuild_rowid, entity_id
                        FROM entity_catalog
                        WHERE rowid > ? AND rowid <= ?
                        ORDER BY rowid ASC
                        LIMIT ?
                        """,
                        (last_rowid, high_water_rowid, normalized_batch_size),
                    ) as cursor:
                        rows = await cursor.fetchall()
                if not rows:
                    break
                entity_ids = [str(row["entity_id"]) for row in rows]
                last_rowid = int(rows[-1]["rebuild_rowid"])
                await self._embed_entities_if_current(entity_ids)
                processed += len(entity_ids)
                if progress_callback is not None:
                    await progress_callback(processed)
            await host._vector_index.prune_orphans(
                valid_entity_query="SELECT entity_id FROM entity_catalog",
                mutation_guard_factory=self._entity_vector_write_lock,
            )
            verify_active_rebuild_profile(
                embedding_service=host._embedding_service,
                vector_index=host._vector_index,
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
            )
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

    async def _maybe_embed_entity(self, entity_id: str) -> bool:
        try:
            return await self._embed_entity_if_current(entity_id)
        except Exception as exc:
            logger.debug("Failed to embed L2 entity %s: %s", entity_id, exc)
            return False

    async def _embed_entity_if_current(self, entity_id: str) -> bool:
        return await self._embed_entities_if_current([entity_id]) > 0

    async def _embed_entities_if_current(self, entity_ids: list[str]) -> int:
        host = self._embedding_host()
        if not self._vectors_enabled():
            return 0
        pipeline = self._build_embedding_pipeline()
        vector_index = host._vector_index
        if pipeline is None or vector_index is None:
            return 0
        snapshots = [
            snapshot
            for entity_id in dict.fromkeys(entity_ids)
            if (snapshot := await self._load_entity_embedding_snapshot(entity_id)) is not None
            and snapshot.text
        ]
        if not snapshots:
            return 0
        results = await pipeline.prepare_items(
            [
                EmbeddingPipelineItem(
                    parent_id=snapshot.entity_id,
                    chunks=[
                        ChunkedText(
                            chunk_id=snapshot.entity_id,
                            text=snapshot.text,
                            chunk_index=0,
                            char_start=0,
                            char_end=len(snapshot.text),
                            token_estimate=max(1, len(snapshot.text) // 4),
                        )
                    ],
                    metadata={"kind": "entity"},
                    payload=snapshot,
                )
                for snapshot in snapshots
            ]
        )
        if not results:
            return 0
        async with self._entity_vector_write_lock():
            current_results = [
                result
                for result in results
                if isinstance(result.payload, _EntityEmbeddingSnapshot)
                and await self._entity_snapshot_matches(result.payload)
            ]
            if not current_results:
                return 0
            persisted = await pipeline.persist_results(current_results)
            if not persisted:
                return 0
            updated = 0
            for result in persisted:
                snapshot = result.payload
                if not isinstance(snapshot, _EntityEmbeddingSnapshot):
                    continue
                if not await self._entity_snapshot_matches(snapshot):
                    await vector_index.delete_embedding(
                        entity_id=result.parent_id,
                        embedding=result.embeddings[0],
                    )
                    continue
                profile = self._profile_from_embedding_result(result.embeddings[0])
                if await self._update_entity_embedding_state(
                    snapshot=snapshot,
                    status=EMBEDDING_STATUS_READY,
                    profile_id=profile.profile_id,
                    embedded_at=result.embedded_at,
                ):
                    updated += 1
                else:
                    await vector_index.delete_embedding(
                        entity_id=result.parent_id,
                        embedding=result.embeddings[0],
                    )
            return updated

    def _build_embedding_pipeline(self) -> MemoryEmbeddingPipeline | None:
        host = self._embedding_host()
        if host._embedding_service is None or host._vector_index is None:
            return None
        return MemoryEmbeddingPipeline(
            embedding_service=host._embedding_service,
            vector_index=host._vector_index,
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )

    async def _load_entity_embedding_snapshot(
        self,
        entity_id: str,
    ) -> _EntityEmbeddingSnapshot | None:
        host = self._embedding_host()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            return await self._load_entity_embedding_snapshot_on_connection(db, entity_id)

    async def _load_entity_embedding_snapshot_on_connection(
        self,
        db: aiosqlite.Connection,
        entity_id: str,
    ) -> _EntityEmbeddingSnapshot | None:
        async with db.execute(
            """
            SELECT entity_id, canonical_name, entity_type, updated_at,
                   embedding_status, embedding_profile_id, last_embedded_at
            FROM entity_catalog
            WHERE entity_id = ?
            """,
            (entity_id,),
        ) as cursor:
            entity = await cursor.fetchone()
        if entity is None:
            return None
        async with db.execute(
            """
            SELECT alias_text
            FROM entity_aliases
            WHERE entity_id = ?
            ORDER BY normalized_alias ASC
            """,
            (entity_id,),
        ) as cursor:
            alias_rows = await cursor.fetchall()
        aliases = tuple(str(row["alias_text"]) for row in alias_rows)
        canonical_name = str(entity["canonical_name"] or "")
        entity_type = str(entity["entity_type"] or "")
        text = build_l2_entity_embedding_text(
            canonical_name=canonical_name,
            entity_type=entity_type,
            aliases=list(aliases),
        )
        return _EntityEmbeddingSnapshot(
            entity_id=str(entity["entity_id"]),
            canonical_name=canonical_name,
            entity_type=entity_type,
            aliases=aliases,
            text=str(text),
            updated_at=float(entity["updated_at"]),
            embedding_status=str(entity["embedding_status"] or EMBEDDING_STATUS_DISABLED),
            embedding_profile_id=(
                str(entity["embedding_profile_id"])
                if entity["embedding_profile_id"] is not None
                else None
            ),
            last_embedded_at=(
                float(entity["last_embedded_at"])
                if entity["last_embedded_at"] is not None
                else None
            ),
        )

    async def _entity_snapshot_matches(self, snapshot: _EntityEmbeddingSnapshot) -> bool:
        current = await self._load_entity_embedding_snapshot(snapshot.entity_id)
        return current == snapshot

    def _entity_vector_write_lock(self) -> asyncio.Lock:
        host = self._embedding_host()
        index = host._vector_index
        if index is None:
            raise RuntimeError("L2 entity vector index is unavailable")
        coordinator = getattr(index, "_coordinator", None)
        if coordinator is not None:
            return cast(asyncio.Lock, coordinator.source_write_lock)
        lock = getattr(index, "_magi_source_embedding_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(index, "_magi_source_embedding_lock", lock)
        return cast(asyncio.Lock, lock)

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
        snapshot: _EntityEmbeddingSnapshot,
        status: str,
        profile_id: str | None,
        embedded_at: float | None,
    ) -> bool:
        host = self._embedding_host()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                current = await self._load_entity_embedding_snapshot_on_connection(
                    db,
                    snapshot.entity_id,
                )
                if current != snapshot:
                    await db.rollback()
                    return False
                cursor = await db.execute(
                    """
                    UPDATE entity_catalog
                    SET embedding_status = ?, embedding_profile_id = ?,
                        last_embedded_at = ?, updated_at = updated_at
                    WHERE entity_id = ?
                    """,
                    (status, profile_id, embedded_at, snapshot.entity_id),
                )
                await db.commit()
                return int(cursor.rowcount) == 1
            except BaseException:
                await asyncio.shield(db.rollback())
                raise

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
        entities = [
            entity
            for entity in await host._list_entities(limit=len(hit_ids), entity_ids=hit_ids)
            if entity.get("embedding_status") == EMBEDDING_STATUS_READY
        ]
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
