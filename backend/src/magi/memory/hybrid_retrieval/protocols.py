"""Structural typing protocols for hybrid retrieval store dependencies.

These protocols document the interfaces that handler classes expect from
their injected store objects, replacing bare ``Any`` annotations with
explicit contracts that can be verified by static type checkers.

NOTE: L1/L3/L4 handlers still depend on store internals (``_row_to_dict``,
``db_path`` for raw SQL) — those will need store-side refactoring before
protocols are practical.  Only L2-related interfaces are defined here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# L2 knowledge-graph store
# ---------------------------------------------------------------------------


@runtime_checkable
class L2StoreProtocol(Protocol):
    """Interface expected by :class:`L2Handler` from the L2 knowledge-graph store."""

    async def batch_get_tom_snapshots(
        self,
        entities: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]: ...

    async def batch_list_tom_assertions(
        self,
        entity_ids: List[str],
        trait_families: List[str] | None = ...,
        validation_states: List[str] | None = ...,
        include_expired: bool = ...,
        target_entity_id: str | None = ...,
        limit_per_entity: int = ...,
    ) -> Dict[str, List[Dict[str, Any]]]: ...

    async def list_tom_assertions(
        self,
        trait_families: List[str] | None = ...,
        validation_states: List[str] | None = ...,
        include_expired: bool = ...,
        target_entity_id: str | None = ...,
        limit: int = ...,
    ) -> List[Dict[str, Any]]: ...

    async def batch_get_relationships(
        self,
        entity_ids: List[str],
        direction: str = ...,
        status_filters: List[str] | None = ...,
        predicates: List[str] | None = ...,
        target_object_id: str | None = ...,
        object_types: List[str] | None = ...,
        limit_per_entity: int = ...,
    ) -> Dict[str, List[Dict[str, Any]]]: ...

    async def get_relationships(
        self,
        subject_id: str | None = ...,
        object_id: str | None = ...,
        predicates: List[str] | None = ...,
        status_filters: List[str] | None = ...,
        object_types: List[str] | None = ...,
        limit: int = ...,
    ) -> List[Dict[str, Any]]: ...

    async def filter_entity_ids_by_facet(
        self,
        entity_ids: List[str],
        facet_name: str,
        facet_values: List[str],
    ) -> List[str]: ...

    async def search_edges_by_embedding(
        self,
        vector_index: Any,
        embedding: Any,
        limit: int,
        status_filters: List[str] | None = ...,
        predicates: List[str] | None = ...,
    ) -> List[Dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Entity catalog (entity resolution)
# ---------------------------------------------------------------------------


@runtime_checkable
class EntityCatalogProtocol(Protocol):
    """Interface expected by :class:`L2Handler` for entity resolution."""

    async def resolve_query_entities(
        self,
        query: str,
        limit: int = ...,
        entity_types: Optional[List[str]] = ...,
    ) -> List[Dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Embedding service
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingServiceProtocol(Protocol):
    """Interface expected by :class:`L2Handler` for text embedding."""

    async def embed_text(self, text: str) -> Any: ...
