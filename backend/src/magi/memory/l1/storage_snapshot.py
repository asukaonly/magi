"""Validated logical event state, independent of SQL dialects and vector backends."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..event_contracts import AuthorType, ContentType, MemoryDomain, RetentionClass
from .embeddings.common import EmbeddingStatus
from ..evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope


from magi_plugin_sdk.storage_models.event_snapshot import (
    SnapshotRecord,
    FactSnapshot,
    SessionSequenceSnapshot,
    EventEmbeddingSnapshot,
    PayloadSnapshot,
    CognitionHandoffSnapshot,
    FacetSnapshot,
    EmbeddingProfileSnapshot,
    ChunkSnapshot,
    EntityLinkSnapshot,
    ProjectedEntitySnapshot,
    EntityProjectionSnapshot,
    SessionPreviewSnapshot,
    EventStorageSnapshot,
)


class EventStateTransfer(Protocol):
    async def export_state(self) -> EventStorageSnapshot: ...

    async def import_state(
        self, snapshot: EventStorageSnapshot, *, replace: bool = False
    ) -> None: ...
