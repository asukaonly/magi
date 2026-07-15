"""Shared constants and protocol for L1 event embedding mixins."""

from __future__ import annotations

import asyncio
import logging
from enum import IntEnum
from typing import Any, Dict, List, Protocol

import aiosqlite

from ...embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ...embedding.sqlite_vec_index import SqliteVecIndex, VectorSearchHit
from ...event_contracts import MemoryEvent

FACT_EVENTS_TABLE = "fact_events"
L1_EVENT_EMBEDDING_STATE_TABLE = "l1_event_embedding_state"
EMBEDDING_PROFILES_TABLE = "embedding_profiles"
EVENT_CHUNKS_TABLE = "l1_event_chunks"
EMBEDDING_TEXT_BUILDER_VERSION = "l1_content_v2"
EMBEDDING_STATUS_PENDING = "pending"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_FAILED = "failed"
EMBEDDING_STATUS_SKIPPED = "skipped"
EMBEDDING_STATUS_DISABLED = "disabled"


class EmbeddingStatus(IntEnum):
    DISABLED = 1
    PENDING = 2
    READY = 3
    FAILED = 4
    SKIPPED = 5


_EMBEDDING_STATUS_LABELS = {
    EmbeddingStatus.DISABLED: EMBEDDING_STATUS_DISABLED,
    EmbeddingStatus.PENDING: EMBEDDING_STATUS_PENDING,
    EmbeddingStatus.READY: EMBEDDING_STATUS_READY,
    EmbeddingStatus.FAILED: EMBEDDING_STATUS_FAILED,
    EmbeddingStatus.SKIPPED: EMBEDDING_STATUS_SKIPPED,
}

_EMBEDDING_STATUS_BY_LABEL = {label: status for status, label in _EMBEDDING_STATUS_LABELS.items()}


def embedding_status_code(value: int | str | EmbeddingStatus | None) -> int:
    if value is None:
        return int(EmbeddingStatus.DISABLED)
    if isinstance(value, EmbeddingStatus):
        return int(value)
    if isinstance(value, int):
        return int(EmbeddingStatus(value))
    normalized = str(value).strip().lower()
    return int(_EMBEDDING_STATUS_BY_LABEL.get(normalized, EmbeddingStatus.DISABLED))


def embedding_status_label(value: int | str | EmbeddingStatus | None) -> str:
    return _EMBEDDING_STATUS_LABELS[EmbeddingStatus(embedding_status_code(value))]

logger = logging.getLogger("magi.memory.l1.embeddings.events")


class L1EventEmbeddingHostProtocol(Protocol):
    db_path: str
    _embedding_service: MemoryEmbeddingService | None
    _vector_index: SqliteVecIndex | None
    _embedding_queue: asyncio.Queue[MemoryEvent | None] | None
    _embedding_active_count: int
    _embedding_batch_size: int
    _embedding_batch_wait_seconds: float
    _operation_guard_factory: Any | None

    async def initialize(self) -> None: ...

    def _vectors_enabled(self) -> bool: ...

    def _async_embeddings_enabled(self) -> bool: ...

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent: ...

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _resolve_active_embedding_profile_id(self) -> tuple[str | None, dict[str, Any]]: ...

    def get_embedding_text(self, event: MemoryEvent) -> str: ...

    async def _maybe_upsert_event_embedding(self, event: MemoryEvent) -> None: ...

    async def _maybe_upsert_event_embeddings(self, events: list[MemoryEvent]) -> None: ...

    async def _fetch_chunk_rows_by_ids(self, chunk_ids: list[str]) -> list[aiosqlite.Row]: ...

    async def _sync_embedding_profiles(
        self,
        db: aiosqlite.Connection,
        profile_ids: set[str],
        *,
        profiles_by_id: dict[str, EmbeddingProfile],
    ) -> None: ...

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
