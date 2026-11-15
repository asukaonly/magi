"""Shared constants and protocol for L1 event embedding mixins."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Protocol

from ...embedding.embedding_service import MemoryEmbeddingService
from ...embedding.ports import VectorIndex, VectorSearchHit
from ...event_contracts import MemoryEvent
from ..embedding_contracts import EventChunkRecord

if TYPE_CHECKING:
    from ..ports import MemoryEventRecord, MemoryEventRepository

from magi_plugin_sdk.storage_models.embedding_status import (
    FACT_EVENTS_TABLE as FACT_EVENTS_TABLE,
    L1_EVENT_EMBEDDING_STATE_TABLE as L1_EVENT_EMBEDDING_STATE_TABLE,
    EMBEDDING_PROFILES_TABLE as EMBEDDING_PROFILES_TABLE,
    EVENT_CHUNKS_TABLE as EVENT_CHUNKS_TABLE,
    EMBEDDING_TEXT_BUILDER_VERSION as EMBEDDING_TEXT_BUILDER_VERSION,
    EMBEDDING_STATUS_PENDING as EMBEDDING_STATUS_PENDING,
    EMBEDDING_STATUS_READY as EMBEDDING_STATUS_READY,
    EMBEDDING_STATUS_FAILED as EMBEDDING_STATUS_FAILED,
    EMBEDDING_STATUS_SKIPPED as EMBEDDING_STATUS_SKIPPED,
    EMBEDDING_STATUS_DISABLED as EMBEDDING_STATUS_DISABLED,
    EmbeddingStatus as EmbeddingStatus,
    _EMBEDDING_STATUS_LABELS as _EMBEDDING_STATUS_LABELS,
    _EMBEDDING_STATUS_BY_LABEL as _EMBEDDING_STATUS_BY_LABEL,
    embedding_status_code as embedding_status_code,
    embedding_status_label as embedding_status_label,
)


logger = logging.getLogger("magi.memory.l1.embeddings.events")


class L1EventEmbeddingHostProtocol(Protocol):
    event_repository: MemoryEventRepository
    _embedding_service: MemoryEmbeddingService | None
    _vector_index: VectorIndex | None
    _embedding_queue: asyncio.Queue[MemoryEvent | None] | None
    _embedding_active_count: int
    _embedding_generation: int
    _embedding_batch_size: int
    _embedding_batch_wait_seconds: float
    _operation_guard_factory: Any | None

    async def initialize(self) -> None: ...

    def _vectors_enabled(self) -> bool: ...

    def _async_embeddings_enabled(self) -> bool: ...

    def embedding_mutation_guard(self) -> Any: ...

    def _record_to_dict(self, record: MemoryEventRecord) -> Dict[str, Any]: ...

    def _resolve_active_embedding_profile_id(self) -> tuple[str | None, dict[str, Any]]: ...

    def get_embedding_text(self, event: MemoryEvent) -> str: ...

    async def _maybe_upsert_event_embedding(self, event: MemoryEvent) -> None: ...

    async def _maybe_upsert_event_embeddings(self, events: list[MemoryEvent]) -> None: ...

    async def _fetch_chunk_rows_by_ids(self, chunk_ids: list[str]) -> list[EventChunkRecord]: ...

    def _chunk_id_for_event(self, event_id: str, chunk_index: int) -> str: ...

    async def _semantic_search_event_hits(
        self, *, query: str, limit: int, user_id: str | None = None
    ) -> list[VectorSearchHit]: ...

    async def _fetch_ranked_events(
        self,
        *,
        hits: list[VectorSearchHit],
        session_id: str | None,
        user_id: str | None,
        event_type: str | None,
        source_filters: List[str] | None,
        domain_filters: List[str] | None,
        l1_retrieval_scopes: List[str] | None,
        limit: int,
    ) -> List[Dict[str, Any]]: ...
