"""Embedding lifecycle helpers for the canonical L1 event store."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.chunking import ChunkedText
from ...embedding.embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from ...embedding.embedding_service import EmbeddingProfile
from ...event_contracts import MemoryDomain, MemoryEvent
from .chunks import L1EventEmbeddingChunkMixin
from .common import (
    EMBEDDING_PROFILES_TABLE,
    EMBEDDING_STATUS_DISABLED,
    EMBEDDING_STATUS_FAILED,
    EMBEDDING_STATUS_PENDING,
    EMBEDDING_STATUS_READY,
    EMBEDDING_STATUS_SKIPPED,
    EMBEDDING_TEXT_BUILDER_VERSION,
    EVENT_CHUNKS_TABLE,
    FACT_EVENTS_TABLE,
    L1_EVENT_EMBEDDING_STATE_TABLE,
    L1EventEmbeddingHostProtocol,
    embedding_status_code,
)
from .profiles import L1EventEmbeddingProfileMixin
from .search import L1EventEmbeddingSearchMixin
from .worker import L1EventEmbeddingWorkerMixin


class L1EventEmbeddingMixin(
    L1EventEmbeddingProfileMixin,
    L1EventEmbeddingChunkMixin,
    L1EventEmbeddingSearchMixin,
    L1EventEmbeddingWorkerMixin,
):
    """Embedding pipeline lifecycle and event embedding state helpers."""

    async def rebuild_embeddings(
        self,
        *,
        batch_size: int = 100,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> int:
        """Rebuild all persisted L1 embeddings from the parent event rows."""
        host = cast(L1EventEmbeddingHostProtocol, self)
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
            reset_at = time.time()
            await db.execute(
                f"""
                UPDATE {L1_EVENT_EMBEDDING_STATE_TABLE}
                SET embedding_status = ?, embedding_profile_id = NULL, embedding_chunk_count = 0, last_embedded_at = NULL, updated_at = ?
                WHERE event_id IN (
                    SELECT event_id FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL
                )
                """,
                (embedding_status_code(EMBEDDING_STATUS_DISABLED), reset_at),
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
            if progress_callback is not None:
                await progress_callback(processed)
        return processed

    async def _maybe_upsert_event_embedding(self, event: MemoryEvent) -> None:
        await self._maybe_upsert_event_embeddings([event])

    async def _maybe_upsert_event_embeddings(self, events: list[MemoryEvent]) -> None:
        host = cast(L1EventEmbeddingHostProtocol, self)
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
                        embedding_status_code(EMBEDDING_STATUS_FAILED),
                        self._initial_embedding_profile_id(event),
                        0,
                        None,
                    )
                    for event in eligible_events
                ]
            )
            return
        state_updates: list[tuple[str, int, str | None, int, float | None]] = []
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
                        embedding_status_code(EMBEDDING_STATUS_READY),
                        profile.profile_id,
                        len(chunks),
                        embedded_at,
                    )
                )
        for event, profile_id in failed_events:
            state_updates.append((event.event_id, embedding_status_code(EMBEDDING_STATUS_FAILED), profile_id, 0, None))
        if state_updates:
            await self._update_event_embedding_states(state_updates, profiles_by_id=profiles_by_id)

    def _build_embedding_pipeline(self) -> MemoryEmbeddingPipeline | None:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if host._embedding_service is None or host._vector_index is None:
            return None
        return MemoryEmbeddingPipeline(
            embedding_service=host._embedding_service,
            vector_index=host._vector_index,
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )

    def _embedding_eligible(self, event: MemoryEvent) -> bool:
        return event.memory_domain not in {
            MemoryDomain.RUNTIME_TELEMETRY,
            MemoryDomain.SYSTEM_CONTROL,
        }

    def _initial_embedding_status(self, event: MemoryEvent) -> str:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if not host._vectors_enabled() or host._embedding_service is None:
            return EMBEDDING_STATUS_DISABLED
        if not self._embedding_eligible(event):
            return EMBEDDING_STATUS_SKIPPED
        return EMBEDDING_STATUS_PENDING

    def _initial_embedding_profile_id(self, event: MemoryEvent) -> str | None:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if (
            not host._vectors_enabled()
            or host._embedding_service is None
            or not self._embedding_eligible(event)
        ):
            return None
        return self.get_active_embedding_profile_id()

    async def _update_event_embedding_states(
        self,
        updates: list[tuple[str, int, str | None, int, float | None]],
        *,
        profiles_by_id: dict[str, EmbeddingProfile] | None = None,
    ) -> None:
        if not updates:
            return
        host = cast(L1EventEmbeddingHostProtocol, self)
        profile_ids = {profile_id for _, _, profile_id, _, _ in updates if profile_id}
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            if profile_ids:
                await self._sync_embedding_profiles(
                    db, profile_ids, profiles_by_id=profiles_by_id or {}
                )
            updated_at = time.time()
            await db.executemany(
                f"""
                UPDATE {L1_EVENT_EMBEDDING_STATE_TABLE}
                SET embedding_status = ?, embedding_profile_id = ?, embedding_chunk_count = ?, last_embedded_at = ?, updated_at = ?
                WHERE event_id = ?
                """,
                [
                    (status, profile_id, int(chunk_count), embedded_at, updated_at, event_id)
                    for event_id, status, profile_id, chunk_count, embedded_at in updates
                ],
            )
            await db.commit()


__all__ = ["L1EventEmbeddingMixin"]
