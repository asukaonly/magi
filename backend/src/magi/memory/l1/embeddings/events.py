"""Embedding lifecycle helpers for the canonical L1 event store."""

from __future__ import annotations

from typing import Awaitable, Callable, cast

from ...embedding.embedding_pipeline import (
    EmbeddingPipelineItem,
    EmbeddingPipelineResult,
    MemoryEmbeddingPipeline,
    partition_embedding_pipeline_items,
    verify_active_rebuild_profile,
)
from ...event_contracts import MemoryDomain, MemoryEvent
from ...operation_barrier import optional_operation_guard
from ..embedding_contracts import EventEmbeddingPublication, EventEmbeddingSource
from .chunks import L1EventEmbeddingChunkMixin
from .common import (
    EMBEDDING_STATUS_DISABLED,
    EMBEDDING_STATUS_PENDING,
    EMBEDDING_STATUS_SKIPPED,
    EMBEDDING_TEXT_BUILDER_VERSION,
    L1EventEmbeddingHostProtocol,
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

    async def count_pending_embeddings(self) -> int:
        host = cast(L1EventEmbeddingHostProtocol, self)
        return await host.event_repository.count_pending_embeddings()

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

        high_water_id = await host.event_repository.event_scan_high_water()

        processed = 0
        last_id = 0
        async with host._vector_index.rebuild_session():
            while last_id < high_water_id:
                page = await host.event_repository.embedding_rebuild_page(
                    after=last_id, through=high_water_id, limit=normalized_batch_size,
                )
                if not page:
                    break
                last_id = page[-1][0]
                events = [event for _sequence, event in page]
                await self._maybe_upsert_event_embeddings(events)
                processed += len(events)
                if progress_callback is not None:
                    await progress_callback(processed)
            await host._vector_index.prune_orphans(
                valid_entity_ids=host.event_repository.visible_embedding_chunk_ids,
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
        generation = host._embedding_generation
        pipeline_items = self._event_embedding_pipeline_items(events)
        embeddable_items, unembeddable_items = partition_embedding_pipeline_items(pipeline_items)
        await self._remove_unembeddable_event_embeddings(unembeddable_items)

        pipeline = self._build_embedding_pipeline()
        if pipeline is None or not embeddable_items:
            return
        snapshots = {
            item.parent_id: EventEmbeddingSource.from_event(cast(MemoryEvent, item.payload))
            for item in embeddable_items
        }
        prepared_results = await pipeline.prepare_items(embeddable_items)
        async with optional_operation_guard(host._operation_guard_factory):
            async with host.embedding_mutation_guard():
                if host._embedding_generation != generation:
                    return
                current_events = await self._current_embedding_events(snapshots)
                if not current_events:
                    return
                current_event_ids = {event.event_id for event in current_events}
                results = await pipeline.persist_results(
                    [result for result in prepared_results if result.parent_id in current_event_ids]
                )
                await host.event_repository.publish_event_embeddings(
                    self._event_embedding_publications(current_events, results),
                )

    async def _remove_unembeddable_event_embeddings(
        self, items: list[EmbeddingPipelineItem],
    ) -> None:
        if not items:
            return
        host = cast(L1EventEmbeddingHostProtocol, self)
        snapshots = {
            item.parent_id: EventEmbeddingSource.from_event(item.payload)
            for item in items if isinstance(item.payload, MemoryEvent)
        }
        if not snapshots:
            return
        async with optional_operation_guard(host._operation_guard_factory):
            async with host.embedding_mutation_guard():
                current = await host.event_repository.get_embedding_sources(list(snapshots))
                removable = [
                    snapshot for event in current
                    if (snapshot := snapshots.get(event.event_id)) == EventEmbeddingSource.from_event(event)
                    and not (self._embedding_eligible(event) and self._build_event_embedding_chunks(event))
                ]
                detached = await host.event_repository.remove_event_embedding_chunks(removable)
                if host._vector_index is not None:
                    for chunk_id in dict.fromkeys(detached):
                        await host._vector_index.delete_entity(entity_id=chunk_id)

    async def _current_embedding_events(
        self, snapshots: dict[str, EventEmbeddingSource],
    ) -> list[MemoryEvent]:
        host = cast(L1EventEmbeddingHostProtocol, self)
        current = await host.event_repository.get_embedding_sources(list(snapshots))
        return [event for event in current if EventEmbeddingSource.from_event(event) == snapshots[event.event_id]]

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
        host = cast(L1EventEmbeddingHostProtocol, self)
        await host.event_repository.publish_event_embeddings([
            self._failed_event_embedding_update(event) for event in events
        ])

    def _event_embedding_publications(
        self, eligible_events: list[MemoryEvent], results: list[EmbeddingPipelineResult],
    ) -> list[EventEmbeddingPublication]:
        publications: list[EventEmbeddingPublication] = []
        by_event = {result.parent_id: result for result in results}
        for event in eligible_events:
            result = by_event.get(event.event_id)
            if result is None:
                publications.append(self._failed_event_embedding_update(event))
                continue
            profile = self._profile_from_embedding_result(result.embeddings[0])
            publications.append(EventEmbeddingPublication(
                source=EventEmbeddingSource.from_event(event), status="ready",
                profile_id=profile.profile_id, profile=profile,
                chunks=tuple(result.chunks), embedded_at=result.embedded_at,
            ))
        return publications


    def _failed_event_embedding_update(self, event: MemoryEvent) -> EventEmbeddingPublication:
        host = cast(L1EventEmbeddingHostProtocol, self)
        profile_id = self._initial_embedding_profile_id(event)
        getter = getattr(host._embedding_service, "get_active_profile", None)
        profile = getter(text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION) if callable(getter) else None
        return EventEmbeddingPublication(
            source=EventEmbeddingSource.from_event(event), status="failed",
            profile_id=profile_id,
            profile=profile if profile is not None and profile.profile_id == profile_id else None,
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



__all__ = ["L1EventEmbeddingMixin"]
