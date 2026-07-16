"""Embedding lifecycle helpers for the canonical L1 event store."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.chunking import ChunkedText
from ...embedding.embedding_pipeline import (
    EmbeddingPipelineItem,
    EmbeddingPipelineResult,
    MemoryEmbeddingPipeline,
    partition_embedding_pipeline_items,
    verify_active_rebuild_profile,
)
from ...embedding.embedding_service import EmbeddingProfile
from ...event_contracts import MemoryDomain, MemoryEvent
from ...operation_barrier import optional_operation_guard
from .chunks import L1EventEmbeddingChunkMixin
from .common import (
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


_EventEmbeddingStateUpdate = tuple[str, int, str | None, int, float | None]
_SuccessfulEventEmbedding = tuple[
    MemoryEvent,
    list[ChunkedText],
    list[Any],
    EmbeddingProfile,
]


@dataclass
class _EventEmbeddingUpsertOutcome:
    state_updates: list[_EventEmbeddingStateUpdate] = field(default_factory=list)
    profiles_by_id: dict[str, EmbeddingProfile] = field(default_factory=dict)
    successful_events: list[_SuccessfulEventEmbedding] = field(default_factory=list)


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

        async with sqlite_connection_async(host.db_path, profile="readonly") as db:
            async with db.execute(
                f"SELECT COALESCE(MAX(id), 0) FROM {FACT_EVENTS_TABLE}"
            ) as cursor:
                row = await cursor.fetchone()
        high_water_id = int(row[0] or 0) if row is not None else 0

        processed = 0
        last_id = 0
        async with host._vector_index.rebuild_session():
            while last_id < high_water_id:
                async with sqlite_connection_async(host.db_path, profile="readonly") as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        f"""
                        SELECT *
                        FROM {FACT_EVENTS_TABLE}
                        WHERE id > ? AND id <= ? AND deleted_at IS NULL
                        ORDER BY id ASC
                        LIMIT ?
                        """,
                        (last_id, high_water_id, normalized_batch_size),
                    ) as cursor:
                        rows = await cursor.fetchall()
                if not rows:
                    break
                last_id = int(rows[-1]["id"])
                events = [host._row_to_memory_event(row) for row in rows]
                await self._maybe_upsert_event_embeddings(events)
                processed += len(events)
                if progress_callback is not None:
                    await progress_callback(processed)
            await host._vector_index.prune_orphans(
                valid_entity_query=f"""
                    SELECT chunks.chunk_id AS entity_id
                    FROM {EVENT_CHUNKS_TABLE} AS chunks
                    JOIN {FACT_EVENTS_TABLE} AS events
                      ON events.event_id = chunks.event_id
                    WHERE events.deleted_at IS NULL
                      AND events.memory_domain NOT IN (?, ?)
                """,
                parameters=(
                    int(MemoryDomain.RUNTIME_TELEMETRY),
                    int(MemoryDomain.SYSTEM_CONTROL),
                ),
                mutation_guard_factory=host.embedding_mutation_guard,
            )
            verify_active_rebuild_profile(
                embedding_service=host._embedding_service,
                vector_index=host._vector_index,
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
            )
        return processed

    async def _maybe_upsert_event_embedding(self, event: MemoryEvent) -> None:
        await self._maybe_upsert_event_embeddings([event])

    async def _maybe_upsert_event_embeddings(self, events: list[MemoryEvent]) -> None:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if not host._vectors_enabled():
            return
        pipeline_items = self._event_embedding_pipeline_items(events)
        embeddable_items, unembeddable_items = partition_embedding_pipeline_items(pipeline_items)
        await self._remove_unembeddable_event_embeddings(unembeddable_items)

        pipeline = self._build_embedding_pipeline()
        if pipeline is None or not embeddable_items:
            return
        prepared_results = await pipeline.prepare_items(embeddable_items)
        embeddable_events = [cast(MemoryEvent, item.payload) for item in embeddable_items]
        async with optional_operation_guard(host._operation_guard_factory):
            async with host.embedding_mutation_guard():
                current_events = await self._current_embedding_events(embeddable_events)
                if not current_events:
                    return
                current_event_ids = {event.event_id for event in current_events}
                results = await pipeline.persist_results(
                    [result for result in prepared_results if result.parent_id in current_event_ids]
                )
                outcome = self._event_embedding_upsert_outcome(current_events, results)
                if outcome.successful_events:
                    await self._replace_event_chunks(outcome.successful_events)
                if outcome.state_updates:
                    await self._update_event_embedding_states(
                        outcome.state_updates,
                        profiles_by_id=outcome.profiles_by_id,
                    )

    async def _remove_unembeddable_event_embeddings(
        self,
        items: list[EmbeddingPipelineItem],
    ) -> None:
        """Remove published chunks only for current parents with no canonical text."""
        if not items:
            return
        host = cast(L1EventEmbeddingHostProtocol, self)
        snapshots = {
            item.parent_id: cast(MemoryEvent, item.payload)
            for item in items
            if isinstance(item.payload, MemoryEvent)
        }
        if not snapshots:
            return

        detached_chunk_ids: list[str] = []
        async with optional_operation_guard(host._operation_guard_factory):
            async with host.embedding_mutation_guard():
                placeholders = ", ".join("?" for _ in snapshots)
                async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
                    db.row_factory = aiosqlite.Row
                    await db.execute("BEGIN IMMEDIATE")
                    try:
                        async with db.execute(
                            f"""
                            SELECT *
                            FROM {FACT_EVENTS_TABLE}
                            WHERE event_id IN ({placeholders}) AND deleted_at IS NULL
                            """,
                            tuple(snapshots),
                        ) as cursor:
                            rows = await cursor.fetchall()
                        removable_event_ids: list[str] = []
                        for row in rows:
                            current = host._row_to_memory_event(row)
                            snapshot = snapshots.get(current.event_id)
                            if snapshot is None or not _event_embedding_parent_is_current(
                                host,
                                current=current,
                                embedded=snapshot,
                            ):
                                continue
                            if self._embedding_eligible(
                                current
                            ) and self._build_event_embedding_chunks(current):
                                continue
                            removable_event_ids.append(current.event_id)

                        for event_id in removable_event_ids:
                            async with db.execute(
                                f"SELECT chunk_id FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                                (event_id,),
                            ) as cursor:
                                chunk_rows = await cursor.fetchall()
                            detached_chunk_ids.extend(str(row[0]) for row in chunk_rows)
                            await db.execute(
                                f"DELETE FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                                (event_id,),
                            )
                        if removable_event_ids:
                            updated_at = time.time()
                            await db.executemany(
                                f"""
                                UPDATE {L1_EVENT_EMBEDDING_STATE_TABLE}
                                SET embedding_status = ?, embedding_profile_id = NULL,
                                    embedding_chunk_count = 0, last_embedded_at = NULL,
                                    updated_at = ?
                                WHERE event_id = ?
                                """,
                                [
                                    (
                                        embedding_status_code(EMBEDDING_STATUS_SKIPPED),
                                        updated_at,
                                        event_id,
                                    )
                                    for event_id in removable_event_ids
                                ],
                            )
                        await db.commit()
                    except BaseException:
                        await db.rollback()
                        raise

                if host._vector_index is not None:
                    for chunk_id in dict.fromkeys(detached_chunk_ids):
                        await host._vector_index.delete_entity(entity_id=chunk_id)

    async def _current_embedding_events(
        self,
        events: list[MemoryEvent],
    ) -> list[MemoryEvent]:
        """Keep only event snapshots that still match their persisted parent."""
        host = cast(L1EventEmbeddingHostProtocol, self)
        event_ids = list(dict.fromkeys(event.event_id for event in events))
        if not event_ids:
            return []
        placeholders = ", ".join("?" for _ in event_ids)
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT *
                FROM {FACT_EVENTS_TABLE}
                WHERE event_id IN ({placeholders}) AND deleted_at IS NULL
                """,
                tuple(event_ids),
            ) as cursor:
                rows = await cursor.fetchall()
        current_by_id = {str(row["event_id"]): host._row_to_memory_event(row) for row in rows}
        return [
            event
            for event in events
            if _event_embedding_parent_is_current(
                host,
                current=current_by_id.get(event.event_id),
                embedded=event,
            )
        ]

    def _event_embedding_pipeline_items(
        self,
        events: list[MemoryEvent],
    ) -> list[EmbeddingPipelineItem]:
        return [
            EmbeddingPipelineItem(
                parent_id=event.event_id,
                chunks=(
                    self._build_event_embedding_chunks(event)
                    if self._embedding_eligible(event)
                    else []
                ),
                metadata={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "source": event.source,
                    "partition_value": event.user_id,
                },
                payload=event,
            )
            for event in events
        ]

    async def _mark_event_embeddings_failed(self, events: list[MemoryEvent]) -> None:
        await self._update_event_embedding_states(
            [self._failed_event_embedding_update(event) for event in events]
        )

    def _event_embedding_upsert_outcome(
        self,
        eligible_events: list[MemoryEvent],
        results: list[EmbeddingPipelineResult],
    ) -> _EventEmbeddingUpsertOutcome:
        outcome = _EventEmbeddingUpsertOutcome()
        results_by_event_id = {result.parent_id: result for result in results}
        for event in eligible_events:
            result = results_by_event_id.get(event.event_id)
            if result is None:
                outcome.state_updates.append(self._failed_event_embedding_update(event))
                continue
            profile = self._profile_from_embedding_result(result.embeddings[0])
            outcome.profiles_by_id[profile.profile_id] = profile
            outcome.successful_events.append((event, result.chunks, result.embeddings, profile))
            outcome.state_updates.append(self._ready_event_embedding_update(event, result, profile))
        return outcome

    def _ready_event_embedding_update(
        self,
        event: MemoryEvent,
        result: EmbeddingPipelineResult,
        profile: EmbeddingProfile,
    ) -> _EventEmbeddingStateUpdate:
        return (
            event.event_id,
            embedding_status_code(EMBEDDING_STATUS_READY),
            profile.profile_id,
            len(result.chunks),
            result.embedded_at,
        )

    def _failed_event_embedding_update(self, event: MemoryEvent) -> _EventEmbeddingStateUpdate:
        return (
            event.event_id,
            embedding_status_code(EMBEDDING_STATUS_FAILED),
            self._initial_embedding_profile_id(event),
            0,
            None,
        )

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


def _event_embedding_parent_is_current(
    host: L1EventEmbeddingHostProtocol,
    *,
    current: MemoryEvent | None,
    embedded: MemoryEvent,
) -> bool:
    if current is None:
        return False
    return (
        current.event_type == embedded.event_type
        and current.source == embedded.source
        and current.user_id == embedded.user_id
        and current.memory_domain == embedded.memory_domain
        and host.get_embedding_text(current) == host.get_embedding_text(embedded)
    )
