"""Vector storage contracts independent of index engine and source database."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .embedding_service import EmbeddingResult

EntityVisibility = Callable[[list[str]], Awaitable[set[str]]]
MutationGuard = Callable[[], AbstractAsyncContextManager[None]]
VectorLayer = Literal["l1", "l2_entities", "l2_edges", "l3", "l4"]


class EmbeddingRebuildIdentityChangedError(RuntimeError):
    """A rebuild produced incompatible model or dimension identities."""


@dataclass(slots=True)
class VectorSearchHit:
    entity_id: str
    distance: float


class VectorIndex(Protocol):
    """Derived vectors; source owners authorize every result and orphan removal."""

    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
    def source_write_guard(self) -> AbstractAsyncContextManager[None]: ...
    def rebuild_session(self) -> AbstractAsyncContextManager[None]: ...
    def in_rebuild_session(self) -> bool: ...
    def verify_rebuild_target(
        self, *, model_key: str | None, dimension: int | None = None
    ) -> None: ...
    async def upsert(
        self, *, entity_id: str, embedding: EmbeddingResult, metadata: dict[str, Any] | None = None
    ) -> None: ...
    async def upsert_many(self, items: list[dict[str, Any]]) -> None: ...
    async def delete_entity(self, *, entity_id: str) -> None: ...
    async def delete_embedding(self, *, entity_id: str, embedding: EmbeddingResult) -> None: ...
    async def clear(self) -> None: ...
    async def prune_orphans(
        self,
        *,
        valid_entity_ids: EntityVisibility,
        batch_size: int = 250,
        mutation_guard_factory: MutationGuard | None = None,
    ) -> int: ...
    async def search(
        self,
        *,
        embedding: EmbeddingResult,
        limit: int,
        max_distance: float | None = None,
        partition_value: str | None = None,
    ) -> list[VectorSearchHit]: ...
    async def get_vectors(
        self, *, entity_ids: list[str], model_key: str | None = None, dimension: int | None = None
    ) -> dict[str, list[float]]: ...


class VectorIndexFactory(Protocol):
    def create(self, layer: VectorLayer) -> VectorIndex: ...
    async def clear_all(self) -> None: ...
    async def close(self) -> None: ...
