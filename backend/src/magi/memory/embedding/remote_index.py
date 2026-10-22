"""Single-center vector projection with durable intents and immutable remote IDs."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
from typing import Any, AsyncIterator, Protocol

from .embedding_service import EmbeddingResult
from .ports import (
    EmbeddingRebuildIdentityChangedError,
    EntityVisibility,
    MutationGuard,
    VectorSearchHit,
)
from .projection import VectorProjectionOperation, VectorProjectionRepository, embedding_model_key

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RemoteVectorHit:
    record_id: str
    entity_id: str
    distance: float


class RemoteVectorClient(Protocol):
    async def apply(self, operation: VectorProjectionOperation) -> None: ...
    async def search(
        self, collection: str, vector: list[float], limit: int, partition: str | None
    ) -> list[RemoteVectorHit]: ...
    async def vectors(self, collection: str, record_ids: list[str]) -> dict[str, list[float]]: ...
    async def reconcile(self, collection: str, current_ids: set[str] | None) -> None: ...


@dataclass
class _Rebuild:
    generation: int
    identity: tuple[str, int] | None = None
    changed: bool = False
    active: bool = True
    superseded: set[str] = field(default_factory=set)
    refreshed: set[str] = field(default_factory=set)


class RemoteVectorIndex:
    """The factory owns one instance per layer for the center's entire lifetime."""

    def __init__(
        self,
        *,
        namespace: str,
        backend_identity: str,
        repository: VectorProjectionRepository,
        client: RemoteVectorClient,
        retry_interval: float = 5.0,
        request_timeout: float = 30.0,
        automatic_recovery: bool = True,
    ) -> None:
        self._namespace = namespace
        self._backend_identity = backend_identity
        self._repository = repository
        self._client = client
        self._retry_interval = retry_interval
        self._request_timeout = request_timeout
        self._automatic_recovery = automatic_recovery
        self._source_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._rebuild_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._context: ContextVar[_Rebuild | None] = ContextVar(
            f"remote_vector_rebuild_{id(self)}", default=None
        )
        self._rebuild: _Rebuild | None = None
        self._generation = 0
        self._initialized = False
        self._worker: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            await self._repository.bind(self._namespace, self._backend_identity)
            self._initialized = True
            if self._automatic_recovery:
                self._start_worker()

    def _start_worker(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(
                self._recover(), name=f"vector-projection-{self._namespace}"
            )

    async def start_recovery(self) -> None:
        await self.initialize()
        self._start_worker()

    async def close(self) -> None:
        async with self._init_lock:
            if self._worker is not None:
                self._worker.cancel()
                try:
                    await self._worker
                except asyncio.CancelledError:
                    pass
                self._worker = None
            self._initialized = False

    def source_write_guard(self) -> asyncio.Lock:
        return self._source_lock

    def _session(self) -> _Rebuild | None:
        session = self._context.get()
        return session if session is not None and session.active else None

    def in_rebuild_session(self) -> bool:
        return self._session() is not None

    def _writable(self, entity_id: str) -> bool:
        session = self._session()
        if session is None:
            if self._rebuild is not None:
                self._rebuild.superseded.add(entity_id)
            return True
        return session.generation == self._generation and entity_id not in session.superseded

    def verify_rebuild_target(self, *, model_key: str | None, dimension: int | None = None) -> None:
        session = self._session()
        if session is not None and session.identity is not None:
            if model_key != session.identity[0] or (
                dimension is not None and dimension != session.identity[1]
            ):
                session.changed = True
                raise EmbeddingRebuildIdentityChangedError(
                    "Embedding identity changed during vector rebuild"
                )

    @asynccontextmanager
    async def rebuild_session(self) -> AsyncIterator[None]:
        if self._session() is not None:
            raise RuntimeError("Nested vector rebuild sessions are not supported")
        async with self._rebuild_lock:
            await self.initialize()
            async with self._write_lock:
                session = _Rebuild(self._generation)
                self._rebuild = session
            token = self._context.set(session)
            try:
                yield
                async with self._write_lock:
                    if session.changed:
                        raise EmbeddingRebuildIdentityChangedError(
                            "Embedding identity changed during vector rebuild"
                        )
                    if session.identity is not None and session.generation == self._generation:
                        for entity_id in session.refreshed - session.superseded:
                            for row in await self._repository.current(
                                self._namespace, entity_ids=[entity_id]
                            ):
                                if row.model_key != session.identity[0]:
                                    await self._repository.delete(
                                        self._namespace,
                                        entity_id=entity_id,
                                        model_key=row.model_key,
                                    )
                        await self._drain()
            finally:
                session.active = False
                self._rebuild = None
                self._context.reset(token)

    async def upsert(
        self, *, entity_id: str, embedding: EmbeddingResult, metadata: dict[str, Any] | None = None
    ) -> None:
        await self.upsert_many(
            [{"entity_id": entity_id, "embedding": embedding, "metadata": metadata}]
        )

    async def upsert_many(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        await self.initialize()
        async with self._write_lock:
            session = self._session()
            if session is not None:
                identities = {
                    (embedding_model_key(item["embedding"]), item["embedding"].dimension)
                    for item in items
                }
                if len(identities) != 1 or (
                    session.identity is not None and session.identity not in identities
                ):
                    session.changed = True
                    raise EmbeddingRebuildIdentityChangedError(
                        "Embedding identity changed during vector rebuild"
                    )
                session.identity = next(iter(identities))
            writable = [item for item in items if self._writable(item["entity_id"])]
            await self._repository.upsert_many(self._namespace, writable)
            await self._drain()
            if session is not None:
                session.refreshed.update(item["entity_id"] for item in writable)

    async def delete_entity(self, *, entity_id: str) -> None:
        await self._delete(entity_id, None)

    async def delete_embedding(self, *, entity_id: str, embedding: EmbeddingResult) -> None:
        await self._delete(entity_id, embedding_model_key(embedding))

    async def _delete(self, entity_id: str, model_key: str | None) -> None:
        await self.initialize()
        async with self._write_lock:
            if self._writable(entity_id):
                await self._repository.delete(
                    self._namespace, entity_id=entity_id, model_key=model_key
                )
                session = self._session()
                if session is not None and (
                    model_key is None
                    or (session.identity is not None and model_key == session.identity[0])
                ):
                    session.refreshed.discard(entity_id)
                await self._drain()

    async def clear(self) -> None:
        await self.retire()
        await self.flush()

    async def retire(self) -> None:
        """Fence every old remote write before attempting network cleanup."""
        await self.initialize()
        async with self._write_lock:
            self._generation += 1
            await self._repository.clear(self._namespace)

    async def flush(self) -> None:
        """Publish pending intents and remove obsolete remote revisions."""
        await self.initialize()
        async with self._write_lock:
            await self._drain()
            for collection, active in (await self._repository.collections(self._namespace)).items():
                ids = (
                    await self._repository.record_ids(self._namespace, collection)
                    if active
                    else None
                )
                async with asyncio.timeout(self._request_timeout):
                    await self._client.reconcile(collection, ids)

    async def _drain(self) -> None:
        while operations := await self._repository.pending(self._namespace):
            for operation in operations:
                async with asyncio.timeout(self._request_timeout):
                    await self._client.apply(operation)
                await self._repository.acknowledge(self._namespace, operation)

    async def _recover(self) -> None:
        while True:
            # Let startup governance and normal ingestion run before remote recovery.
            await asyncio.sleep(self._retry_interval)
            try:
                await self.flush()
            except Exception as error:
                logger.warning(
                    "Vector projection recovery deferred",
                    extra={"layer": self._namespace, "error_type": type(error).__name__},
                )

    async def prune_orphans(
        self,
        *,
        valid_entity_ids: EntityVisibility,
        batch_size: int = 250,
        mutation_guard_factory: MutationGuard | None = None,
    ) -> int:
        await self.initialize()
        deleted = 0
        after = ""
        while True:
            async with AsyncExitStack() as stack:
                if mutation_guard_factory is not None:
                    await stack.enter_async_context(mutation_guard_factory())
                await stack.enter_async_context(self._source_lock)
                await stack.enter_async_context(self._write_lock)
                ids = await self._repository.page(
                    self._namespace, after=after, limit=max(1, min(batch_size, 1000))
                )
                if not ids:
                    return deleted
                valid = await valid_entity_ids(ids)
                if not isinstance(valid, set) or not valid.issubset(ids):
                    raise ValueError("Source visibility returned invalid entity IDs")
                for entity_id in set(ids) - valid:
                    if self._writable(entity_id):
                        await self._repository.delete(self._namespace, entity_id=entity_id)
                        deleted += 1
                await self._drain()
                after = ids[-1]

    async def search(
        self,
        *,
        embedding: EmbeddingResult,
        limit: int,
        max_distance: float | None = None,
        partition_value: str | None = None,
    ) -> list[VectorSearchHit]:
        if limit <= 0:
            return []
        await self.initialize()
        async with self._write_lock:
            key = embedding_model_key(embedding)
            hits: list[VectorSearchHit] = []
            for collection in await self._repository.search_collections(
                self._namespace, key, embedding.dimension
            ):
                # Stale remote IDs are excluded before ranking the visible results.
                current_ids = await self._repository.record_ids(self._namespace, collection)
                count = min(max(limit * 2, 32), max(1, len(current_ids)))
                while True:
                    async with asyncio.timeout(self._request_timeout):
                        remote = await self._client.search(
                            collection, embedding.vector, count, partition_value
                        )
                    rows = await self._repository.current(
                        self._namespace, entity_ids=list({hit.entity_id for hit in remote})
                    )
                    current = {
                        (row.record_id, row.entity_id)
                        for row in rows
                        if row.published
                        and row.model_key == key
                        and row.dimension == embedding.dimension
                        and (partition_value is None or row.partition_value == partition_value)
                    }
                    visible = [
                        VectorSearchHit(hit.entity_id, hit.distance)
                        for hit in remote
                        if (hit.record_id, hit.entity_id) in current
                        and (max_distance is None or hit.distance <= max_distance)
                    ]
                    if len(visible) >= limit or len(remote) < count:
                        hits.extend(visible)
                        break
                    count *= 2
            return sorted(hits, key=lambda hit: (hit.distance, hit.entity_id))[:limit]

    async def get_vectors(
        self, *, entity_ids: list[str], model_key: str | None = None, dimension: int | None = None
    ) -> dict[str, list[float]]:
        await self.initialize()
        async with self._write_lock:
            rows = [
                row
                for row in await self._repository.current(self._namespace, entity_ids=entity_ids)
                if row.published
                and (model_key is None or row.model_key == model_key)
                and (dimension is None or row.dimension == dimension)
            ]
            result: dict[str, list[float]] = {}
            for collection in {row.collection_id for row in rows}:
                selected = [row for row in rows if row.collection_id == collection]
                async with asyncio.timeout(self._request_timeout):
                    vectors = await self._client.vectors(
                        collection, [row.record_id for row in selected]
                    )
                for row in selected:
                    if row.record_id in vectors:
                        if len(vectors[row.record_id]) != row.dimension:
                            raise ValueError(
                                "Remote vector dimension does not match its current identity"
                            )
                        result[row.entity_id] = vectors[row.record_id]
            return result
