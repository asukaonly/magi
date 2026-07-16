"""Canonical L1 event store for normalized memory events."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from ..embedding.embedding_service import MemoryEmbeddingService
from ..embedding.sqlite_vec_index import SqliteVecIndex
from ..event_contracts import MemoryEvent
from .embeddings.common import (
    EMBEDDING_PROFILES_TABLE,
    EMBEDDING_TEXT_BUILDER_VERSION,
    EVENT_CHUNKS_TABLE,
    FACT_EVENTS_TABLE,
)
from .embeddings.events import L1EventEmbeddingMixin
from .entities.links import L1EventEntityMixin
from .lifecycle import (
    DEFAULT_EMBEDDING_WORKER_COUNT,
    EMBEDDING_QUEUE_MAXSIZE,
    L1EventLifecycleMixin,
)
from .retrieval.fts import L1EventFtsMixin
from .retrieval.queries import L1EventQueryMixin
from .source_facets import L1SourceFacetMixin
from .storage.rows import L1EventRowMixin
from .writes import L1EventWriteMixin, L1_STORE_DIAGNOSTIC_EVENT_TYPES


class L1EventStore(
    L1EventEntityMixin,
    L1EventRowMixin,
    L1EventFtsMixin,
    L1EventLifecycleMixin,
    L1EventEmbeddingMixin,
    L1EventQueryMixin,
    L1SourceFacetMixin,
    L1EventWriteMixin,
):
    """Stores immutable normalized memory events in SQLite."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memory/l1_events.db",
        embedding_service: MemoryEmbeddingService | None = None,
        memory_config_getter: Callable[[], Any] | None = None,
        vector_enabled: bool = True,
        async_embeddings: bool = True,
        embedding_worker_count: int = DEFAULT_EMBEDDING_WORKER_COUNT,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._memory_config_getter = memory_config_getter
        self._default_vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._default_async_embeddings = bool(async_embeddings)
        self._embedding_worker_count = max(1, int(embedding_worker_count))
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l1_event_chunk_vectors",
                entity_column="chunk_id",
                vec_table_prefix="l1_event_vec",
                partition_key_column="user_id",
            )
            if embedding_service is not None or vector_enabled
            else None
        )
        self._embedding_queue: asyncio.Queue[MemoryEvent | None] | None = (
            asyncio.Queue(maxsize=max(EMBEDDING_QUEUE_MAXSIZE, self._embedding_worker_count))
            if embedding_service is not None
            else None
        )
        self._embedding_workers: list[asyncio.Task[None]] = []
        self._embedding_active_count = 0
        self._embedding_batch_size = 5
        self._embedding_batch_wait_seconds = 1.0
        self._embedding_mutation_lock = asyncio.Lock()
        self._operation_guard_factory: Callable[[], Any] | None = None
        self._initialized = False
        self._pinned_payload_store: Any | None = None

    @asynccontextmanager
    async def embedding_mutation_guard(self) -> AsyncIterator[None]:
        """Serialize parent validation with vector and chunk publication."""
        async with self._embedding_mutation_lock:
            yield

    async def get_pinned_payloads(self, event_ids: list[str]) -> dict[str, str]:
        """Return ``{event_id: pinned full text}`` for events that have one (RFC #56 P3).

        Reads the ``l1_event_payload`` satellite; events without a pinned payload
        are simply absent from the result, so L2 falls back to ``content``.
        """
        if self._pinned_payload_store is None:
            from .event_payload_store import L1EventPayloadStore

            self._pinned_payload_store = L1EventPayloadStore(db_path=self.db_path)
        return await self._pinned_payload_store.get_many(list(event_ids))

    async def prune_pinned_payloads(
        self, *, retention_seconds: float, now: float | None = None
    ) -> int:
        """Delete pinned full-text payloads older than the retention window (RFC #56 P3).

        Run from L1 retention maintenance; pinned payloads are a transient
        extraction aid (consumed by L2 shortly after ingest), so they are pruned
        without touching the parent event. Returns the number of rows deleted.
        """
        if self._pinned_payload_store is None:
            from .event_payload_store import L1EventPayloadStore

            self._pinned_payload_store = L1EventPayloadStore(db_path=self.db_path)
        return await self._pinned_payload_store.prune_stale(
            retention_seconds=retention_seconds, now=now
        )


__all__ = [
    "DEFAULT_EMBEDDING_WORKER_COUNT",
    "EMBEDDING_PROFILES_TABLE",
    "EMBEDDING_QUEUE_MAXSIZE",
    "EMBEDDING_TEXT_BUILDER_VERSION",
    "EVENT_CHUNKS_TABLE",
    "FACT_EVENTS_TABLE",
    "L1EventStore",
    "L1_STORE_DIAGNOSTIC_EVENT_TYPES",
]
