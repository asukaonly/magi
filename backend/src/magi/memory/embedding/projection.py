"""Durable desired-state contracts for remote vector projections."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .embedding_service import EmbeddingResult


@dataclass(frozen=True, slots=True)
class VectorProjection:
    entity_id: str
    model_key: str
    dimension: int
    generation: int
    revision: int
    record_id: str
    collection_id: str
    partition_value: str | None
    published: bool


@dataclass(frozen=True, slots=True)
class VectorProjectionOperation:
    operation_id: int
    kind: Literal["upsert", "delete", "clear"]
    collection_id: str
    record_id: str | None
    payload: dict[str, Any] | None


class VectorProjectionRepository(Protocol):
    async def bind(self, namespace: str, backend_identity: str) -> None: ...
    async def upsert(
        self,
        namespace: str,
        *,
        entity_id: str,
        embedding: EmbeddingResult,
        metadata: dict[str, Any] | None,
    ) -> VectorProjection: ...
    async def upsert_many(
        self, namespace: str, items: list[dict[str, Any]]
    ) -> list[VectorProjection]: ...
    async def delete(
        self, namespace: str, *, entity_id: str, model_key: str | None = None
    ) -> None: ...
    async def clear(self, namespace: str) -> None: ...
    async def current(
        self, namespace: str, *, entity_ids: list[str] | None = None
    ) -> list[VectorProjection]: ...
    async def pending(
        self, namespace: str, *, limit: int = 100
    ) -> list[VectorProjectionOperation]: ...
    async def collections(self, namespace: str) -> dict[str, bool]: ...
    async def record_ids(self, namespace: str, collection_id: str) -> set[str]: ...
    async def search_collections(
        self, namespace: str, model_key: str, dimension: int
    ) -> list[str]: ...
    async def page(self, namespace: str, *, after: str, limit: int) -> list[str]: ...
    async def acknowledge(self, namespace: str, operation: VectorProjectionOperation) -> None: ...


def embedding_model_key(embedding: EmbeddingResult) -> str:
    return str(embedding.index_identity or embedding.model_identity or embedding.model_name)
