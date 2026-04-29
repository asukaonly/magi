"""Embedding and vector-search helpers for the canonical L1 event store."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.chunking import ChunkedText, chunk_sentences
from ...embedding.embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from ...embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ...embedding.embedding_text_builders import build_l1_embedding_text
from ...embedding.sqlite_vec_index import SqliteVecIndex, VectorSearchHit
from ...event_contracts import MemoryDomain, MemoryEvent

FACT_EVENTS_TABLE = "fact_events"
EMBEDDING_PROFILES_TABLE = "embedding_profiles"
EVENT_CHUNKS_TABLE = "l1_event_chunks"
EMBEDDING_TEXT_BUILDER_VERSION = "l1_content_v2"
EMBEDDING_STATUS_PENDING = "pending"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_FAILED = "failed"
EMBEDDING_STATUS_SKIPPED = "skipped"
EMBEDDING_STATUS_DISABLED = "disabled"

logger = logging.getLogger(__name__)


class _L1EventEmbeddingHostProtocol(Protocol):
    db_path: str
    _embedding_service: MemoryEmbeddingService | None
    _vector_index: SqliteVecIndex | None
    _embedding_queue: asyncio.Queue[MemoryEvent | None] | None
    _embedding_batch_size: int
    _embedding_batch_wait_seconds: float

    async def initialize(self) -> None: ...

    def _vectors_enabled(self) -> bool: ...

    def _async_embeddings_enabled(self) -> bool: ...

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent: ...

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _resolve_active_embedding_profile_id(self) -> tuple[str | None, dict[str, Any]]: ...


class L1EventEmbeddingMixin:
    """Embedding pipeline, chunk storage, and vector-search helpers."""

    async def rebuild_embeddings(self, *, batch_size: int = 100) -> int:
        """Rebuild all persisted L1 embeddings from the parent event rows."""
        host = cast(_L1EventEmbeddingHostProtocol, self)
        await host.initialize()
        normalized_batch_size = max(1, int(batch_size))
        if (
            not host._vectors_enabled()
            or host._embedding_service is None
            or host._vector_index is None
        ):
            return 0

        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            await db.execute(f"DELETE FROM {EVENT_CHUNKS_TABLE}")
            await db.execute(f"DELETE FROM {EMBEDDING_PROFILES_TABLE}")
            await db.execute(
                f"""
                UPDATE {FACT_EVENTS_TABLE}
                SET embedding_status = ?, embedding_profile_id = NULL, embedding_chunk_count = 0, last_embedded_at = NULL
                WHERE deleted_at IS NULL
                """,
                (EMBEDDING_STATUS_DISABLED,),
            )
            await db.commit()
        await host._vector_index.clear()

        processed = 0
        offset = 0
        while True:
            async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    f"""
                    SELECT *
                    FROM {FACT_EVENTS_TABLE}
                    WHERE deleted_at IS NULL
                    ORDER BY timestamp ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (normalized_batch_size, offset),
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                break
            events = [host._row_to_memory_event(row) for row in rows]
            await self._maybe_upsert_event_embeddings(events)
            processed += len(events)
            offset += len(rows)
        return processed

    async def vector_search(
        self,
        *,
        query: str,
        limit: int = 100,
        user_id: Optional[str] = None,
    ) -> list[VectorSearchHit]:
        """Semantic vector search over L1 event chunks."""
        return await self._semantic_search_event_hits(
            query=query,
            limit=limit,
            user_id=user_id,
        )

    async def _maybe_upsert_event_embedding(self, event: MemoryEvent) -> None:
        await self._maybe_upsert_event_embeddings([event])

    async def _maybe_upsert_event_embeddings(self, events: list[MemoryEvent]) -> None:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        if not host._vectors_enabled():
            return
        pipeline = self._build_embedding_pipeline()
        if pipeline is None:
            return
        eligible_events = [event for event in events if self._embedding_eligible(event)]
        if not eligible_events:
            return
        results = await pipeline.upsert_items(
            [
                EmbeddingPipelineItem(
                    parent_id=event.event_id,
                    chunks=self._build_event_embedding_chunks(event),
                    metadata={
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "source": event.source,
                        "partition_value": event.user_id,
                    },
                    payload=event,
                )
                for event in eligible_events
            ]
        )
        if not results:
            await self._update_event_embedding_states(
                [
                    (
                        event.event_id,
                        EMBEDDING_STATUS_FAILED,
                        self._initial_embedding_profile_id(event),
                        0,
                        None,
                    )
                    for event in eligible_events
                ]
            )
            return
        state_updates: list[tuple[str, str, str | None, int, float | None]] = []
        profiles_by_id: dict[str, EmbeddingProfile] = {}
        successful_events: list[
            tuple[MemoryEvent, list[ChunkedText], list[Any], EmbeddingProfile]
        ] = []
        failed_events: list[tuple[MemoryEvent, str | None]] = []
        results_by_event_id = {result.parent_id: result for result in results}
        for event in eligible_events:
            result = results_by_event_id.get(event.event_id)
            if result is None:
                failed_events.append((event, self._initial_embedding_profile_id(event)))
                continue
            profile = self._profile_from_embedding_result(result.embeddings[0])
            profiles_by_id[profile.profile_id] = profile
            successful_events.append((event, result.chunks, result.embeddings, profile))
        if successful_events:
            await self._replace_event_chunks(successful_events)
            for event, chunks, _, profile in successful_events:
                embedded_at = results_by_event_id[event.event_id].embedded_at
                state_updates.append(
                    (
                        event.event_id,
                        EMBEDDING_STATUS_READY,
                        profile.profile_id,
                        len(chunks),
                        embedded_at,
                    )
                )
        for event, profile_id in failed_events:
            state_updates.append((event.event_id, EMBEDDING_STATUS_FAILED, profile_id, 0, None))
        if state_updates:
            await self._update_event_embedding_states(state_updates, profiles_by_id=profiles_by_id)

    def _build_embedding_pipeline(self) -> MemoryEmbeddingPipeline | None:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        if host._embedding_service is None or host._vector_index is None:
            return None
        return MemoryEmbeddingPipeline(
            embedding_service=host._embedding_service,
            vector_index=host._vector_index,
        )

    async def _semantic_search_event_hits(
        self, *, query: str, limit: int, user_id: str | None = None
    ) -> list[VectorSearchHit]:
        host = cast(_L1EventEmbeddingHostProtocol, self)
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
        try:
            return cast(
                list[VectorSearchHit],
                await host._vector_index.search(
                    embedding=embedding, limit=limit, partition_value=user_id
                ),
            )
        except Exception as exc:
            logger.warning("Failed semantic search over L1 events: %s", exc)
            return []

    async def _schedule_event_embedding(self, event: MemoryEvent) -> None:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        if not host._vectors_enabled():
            return
        queue = host._embedding_queue
        if queue is not None and host._async_embeddings_enabled():
            await queue.put(event)
            return
        await self._maybe_upsert_event_embedding(event)

    async def _run_embedding_worker(self) -> None:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        queue = host._embedding_queue
        if queue is None:
            return
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
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
                    next_item = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if next_item is None:
                    queue.task_done()
                    should_stop = True
                    break
                batch.append(next_item)
            try:
                await self._maybe_upsert_event_embeddings(batch)
            finally:
                for _ in batch:
                    queue.task_done()
            if should_stop:
                break

    async def _fetch_ranked_events(
        self,
        *,
        hits: list[VectorSearchHit],
        session_id: Optional[str],
        user_id: Optional[str],
        event_type: Optional[str],
        source_filters: Optional[List[str]],
        domain_filters: Optional[List[str]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        if not hits:
            return []
        query = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
        chunk_ids = [hit.entity_id for hit in hits]
        chunk_rows = await self._fetch_chunk_rows_by_ids(chunk_ids)
        chunk_by_id = {str(row["chunk_id"]): row for row in chunk_rows}
        event_id_order: list[str] = []
        chunks_by_event: dict[str, list[dict[str, Any]]] = {}
        best_distance_by_event: dict[str, float] = {}
        for hit in hits:
            row = chunk_by_id.get(hit.entity_id)
            if row is None:
                continue
            event_id = str(row["event_id"])
            if event_id not in chunks_by_event:
                event_id_order.append(event_id)
                chunks_by_event[event_id] = []
                best_distance_by_event[event_id] = hit.distance
            best_distance_by_event[event_id] = min(best_distance_by_event[event_id], hit.distance)
            chunks_by_event[event_id].append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "chunk_index": int(row["chunk_index"]),
                    "text": str(row["chunk_text"]),
                    "char_start": int(row["char_start"]),
                    "char_end": int(row["char_end"]),
                    "distance": hit.distance,
                }
            )
        if not event_id_order:
            return []

        args: list[Any] = []
        placeholders = ", ".join("?" for _ in event_id_order)
        query += f" AND event_id IN ({placeholders})"
        args.extend(event_id_order)
        if session_id:
            query += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            query += " AND user_id = ?"
            args.append(user_id)
        if event_type:
            query += " AND event_type = ?"
            args.append(event_type)
        if source_filters:
            source_placeholders = ", ".join("?" for _ in source_filters)
            query += f" AND source IN ({source_placeholders})"
            args.extend(source_filters)
        allowed_domains = [MemoryDomain.from_value(value) for value in domain_filters or []]
        if allowed_domains:
            domain_placeholders = ", ".join("?" for _ in allowed_domains)
            query += f" AND memory_domain IN ({domain_placeholders})"
            args.extend(int(domain) for domain in allowed_domains)
        else:
            query += " AND memory_domain != ?"
            args.append(int(MemoryDomain.RUNTIME_TELEMETRY))

        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        events_by_id = {str(row["event_id"]): host._row_to_dict(row) for row in rows}
        ranked: list[Dict[str, Any]] = []
        for event_id in event_id_order:
            event = events_by_id.get(event_id)
            if event is None:
                continue
            event["distance"] = best_distance_by_event[event_id]
            event["matched_chunks"] = chunks_by_event.get(event_id, [])
            ranked.append(event)
            if len(ranked) >= limit:
                break
        return ranked

    def get_embedding_text(self, event: MemoryEvent) -> str:
        return cast(str, build_l1_embedding_text(event))

    def get_active_embedding_profile_id(self) -> str | None:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        profile_id, _ = host._resolve_active_embedding_profile_id()
        return profile_id

    def _embedding_eligible(self, event: MemoryEvent) -> bool:
        return event.memory_domain not in {
            MemoryDomain.RUNTIME_TELEMETRY,
            MemoryDomain.SYSTEM_CONTROL,
        }

    def _initial_embedding_status(self, event: MemoryEvent) -> str:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        if not host._vectors_enabled() or host._embedding_service is None:
            return EMBEDDING_STATUS_DISABLED
        if not self._embedding_eligible(event):
            return EMBEDDING_STATUS_SKIPPED
        return EMBEDDING_STATUS_PENDING

    def _initial_embedding_profile_id(self, event: MemoryEvent) -> str | None:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        if (
            not host._vectors_enabled()
            or host._embedding_service is None
            or not self._embedding_eligible(event)
        ):
            return None
        return self.get_active_embedding_profile_id()

    def _profile_from_embedding_result(self, embedding: Any) -> EmbeddingProfile:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        if host._embedding_service is not None and hasattr(
            host._embedding_service, "profile_from_result"
        ):
            return host._embedding_service.profile_from_result(
                embedding,
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
            )
        return EmbeddingProfile.build(
            provider_name="unknown",
            model_name=str(getattr(embedding, "model_name", "embedding")),
            dimension=int(getattr(embedding, "dimension", 0) or 0),
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )

    async def _update_event_embedding_states(
        self,
        updates: list[tuple[str, str, str | None, int, float | None]],
        *,
        profiles_by_id: dict[str, EmbeddingProfile] | None = None,
    ) -> None:
        if not updates:
            return
        host = cast(_L1EventEmbeddingHostProtocol, self)
        profile_ids = {profile_id for _, _, profile_id, _, _ in updates if profile_id}
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            if profile_ids:
                await self._sync_embedding_profiles(
                    db, profile_ids, profiles_by_id=profiles_by_id or {}
                )
            await db.executemany(
                f"""
                UPDATE {FACT_EVENTS_TABLE}
                SET embedding_status = ?, embedding_profile_id = ?, embedding_chunk_count = ?, last_embedded_at = ?
                WHERE event_id = ?
                """,
                [
                    (status, profile_id, int(chunk_count), embedded_at, event_id)
                    for event_id, status, profile_id, chunk_count, embedded_at in updates
                ],
            )
            await db.commit()

    async def _sync_embedding_profiles(
        self,
        db: aiosqlite.Connection,
        profile_ids: set[str],
        *,
        profiles_by_id: dict[str, EmbeddingProfile],
    ) -> None:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        active_profile = None
        if host._embedding_service is not None and hasattr(
            host._embedding_service, "get_active_profile"
        ):
            active_profile = host._embedding_service.get_active_profile(
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION
            )
        if active_profile is not None:
            profiles_by_id[active_profile.profile_id] = active_profile
        now = time.time()
        for profile_id in profile_ids:
            profile = profiles_by_id.get(profile_id)
            if profile is None:
                continue
            await db.execute(
                f"""
                INSERT OR IGNORE INTO {EMBEDDING_PROFILES_TABLE}(
                    profile_id, provider_name, model_name, embedding_dim, text_builder_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.provider_name,
                    profile.model_name,
                    profile.dimension,
                    profile.text_builder_version,
                    now,
                ),
            )

    def _build_event_embedding_chunks(self, event: MemoryEvent) -> list[ChunkedText]:
        return cast(list[ChunkedText], chunk_sentences(self.get_embedding_text(event)))

    def _chunk_id_for_event(self, event_id: str, chunk_index: int) -> str:
        return f"{event_id}::chunk-{chunk_index}"

    async def _replace_event_chunks(
        self,
        entries: list[tuple[MemoryEvent, list[ChunkedText], list[Any], EmbeddingProfile]],
    ) -> None:
        if not entries:
            return
        host = cast(_L1EventEmbeddingHostProtocol, self)
        now = time.time()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            for event, chunks, _, profile in entries:
                await db.execute(
                    f"DELETE FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                    (event.event_id,),
                )
                await db.executemany(
                    f"""
                    INSERT INTO {EVENT_CHUNKS_TABLE}(
                        chunk_id, event_id, chunk_index, chunk_text, char_start, char_end,
                        token_estimate, embedding_profile_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            self._chunk_id_for_event(event.event_id, chunk.chunk_index),
                            event.event_id,
                            chunk.chunk_index,
                            chunk.text,
                            chunk.char_start,
                            chunk.char_end,
                            chunk.token_estimate,
                            profile.profile_id,
                            now,
                            now,
                        )
                        for chunk in chunks
                    ],
                )
            await db.commit()

    async def _fetch_chunk_rows_by_ids(self, chunk_ids: list[str]) -> list[aiosqlite.Row]:
        if not chunk_ids:
            return []
        host = cast(_L1EventEmbeddingHostProtocol, self)
        placeholders = ", ".join("?" for _ in chunk_ids)
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT chunk_id, event_id, chunk_index, chunk_text, char_start, char_end
                FROM {EVENT_CHUNKS_TABLE}
                WHERE chunk_id IN ({placeholders})
                """,
                tuple(chunk_ids),
            ) as cursor:
                return cast(list[aiosqlite.Row], await cursor.fetchall())

    async def _list_chunk_ids_for_event(self, event_id: str) -> list[str]:
        host = cast(_L1EventEmbeddingHostProtocol, self)
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            async with db.execute(
                f"SELECT chunk_id FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]
