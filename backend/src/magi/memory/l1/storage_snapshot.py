"""Validated logical event state, independent of SQL dialects and vector backends."""

from __future__ import annotations

from typing import Protocol

from magi_plugin_sdk.storage_models.event_snapshot import (
    SnapshotRecord as SnapshotRecord,
    FactSnapshot as FactSnapshot,
    SessionSequenceSnapshot as SessionSequenceSnapshot,
    EventEmbeddingSnapshot as EventEmbeddingSnapshot,
    PayloadSnapshot as PayloadSnapshot,
    CognitionHandoffSnapshot as CognitionHandoffSnapshot,
    FacetSnapshot as FacetSnapshot,
    EmbeddingProfileSnapshot as EmbeddingProfileSnapshot,
    ChunkSnapshot as ChunkSnapshot,
    EntityLinkSnapshot as EntityLinkSnapshot,
    ProjectedEntitySnapshot as ProjectedEntitySnapshot,
    EntityProjectionSnapshot as EntityProjectionSnapshot,
    SessionPreviewSnapshot as SessionPreviewSnapshot,
    EventStorageSnapshot,
)

class EventStateTransfer(Protocol):
    async def export_state(self) -> EventStorageSnapshot: ...

    async def import_state(
        self, snapshot: EventStorageSnapshot, *, replace: bool = False
    ) -> None: ...
