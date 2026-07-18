"""Structural typing protocols for hybrid retrieval store dependencies.

These protocols document the interfaces that handler classes expect from
their injected store objects, replacing bare ``Any`` annotations with
explicit contracts that can be verified by static type checkers.

All layer handlers (L1-L4) now delegate to public store APIs and no
longer access store internals.  The protocols below cover L1-L4 stores.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable


# ---------------------------------------------------------------------------
# L1 event store
# ---------------------------------------------------------------------------


@runtime_checkable
class L1StoreProtocol(Protocol):
    """Interface expected by :class:`L1Handler` from the L1 event store."""

    db_path: str

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = ...,
        user_id: Optional[str] = ...,
        start_time: Optional[float] = ...,
        end_time: Optional[float] = ...,
        strict: bool = ...,
        l1_retrieval_scopes: Optional[List[str]] = ...,
    ) -> List[Tuple[str, float]]: ...

    async def vector_search(
        self,
        *,
        query: str,
        limit: int = ...,
        user_id: Optional[str] = ...,
    ) -> List[Any]: ...

    async def query_events(
        self,
        *,
        session_id: Optional[str] = ...,
        user_id: Optional[str] = ...,
        event_type: Optional[str] = ...,
        source_filters: Optional[List[str]] = ...,
        query: Optional[str] = ...,
        l1_retrieval_scopes: Optional[List[str]] = ...,
        limit: int = ...,
    ) -> List[Dict[str, Any]]: ...

    async def resolve_event_entities(
        self,
        event_ids: List[str],
    ) -> List[str]: ...

    async def find_events_by_entities(
        self,
        entity_ids: List[str],
        *,
        exclude_event_ids: Optional[List[str]] = ...,
        limit: int = ...,
    ) -> List[Tuple[str, int]]: ...

    async def filter_ids_by_user(
        self,
        event_ids: List[str],
        user_id: str,
    ) -> List[str]: ...

    async def fetch_events(
        self,
        event_ids: List[str],
        *,
        session_id: Optional[str] = ...,
        user_id: Optional[str] = ...,
        event_types: Optional[List[str]] = ...,
        source_filters: Optional[List[str]] = ...,
        domain_filters: Optional[List[str]] = ...,
        exclude_domain: Optional[str] = ...,
        time_start: Optional[float] = ...,
        time_end: Optional[float] = ...,
        l1_retrieval_scopes: Optional[List[str]] = ...,
    ) -> List[Dict[str, Any]]: ...


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
        include_superseded: bool = ...,
        target_entity_id: str | None = ...,
        limit_per_entity: int = ...,
    ) -> Dict[str, List[Dict[str, Any]]]: ...

    async def batch_list_current_assertions(
        self,
        *,
        entity_ids: List[str],
        entity_type: str | None = ...,
        trait_families: List[str] | None = ...,
        validation_states: List[str] | None = ...,
        target_entity_id: str | None = ...,
        context_scope: Dict[str, Any] | None = ...,
        effective_at: float | None = ...,
        effective_range: tuple[float | None, float | None] | None = ...,
        include_expired: bool = ...,
        committed_only: bool | None = ...,
        limit_per_entity: int = ...,
    ) -> Dict[str, List[Dict[str, Any]]]: ...

    async def list_tom_assertions(
        self,
        trait_families: List[str] | None = ...,
        validation_states: List[str] | None = ...,
        include_expired: bool = ...,
        include_superseded: bool = ...,
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
        evidence_classes: List[str] | None = ...,
    ) -> Dict[str, List[Dict[str, Any]]]: ...

    async def batch_list_current_relationships(
        self,
        *,
        entity_ids: List[str],
        direction: str = ...,
        object_id: str | None = ...,
        predicates: List[str] | None = ...,
        object_types: List[str] | None = ...,
        evidence_classes: List[str] | None = ...,
        context_scope: Dict[str, Any] | None = ...,
        effective_at: float | None = ...,
        effective_range: tuple[float | None, float | None] | None = ...,
        include_history: bool | None = ...,
        committed_only: bool | None = ...,
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
        evidence_classes: List[str] | None = ...,
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


# ---------------------------------------------------------------------------
# L3 summary store
# ---------------------------------------------------------------------------


@runtime_checkable
class L3StoreProtocol(Protocol):
    """Interface expected by :class:`L3Handler` from the L3 summary store."""

    async def bm25_search(
        self,
        query: str,
        *,
        summary_type: Optional[str] = ...,
        summary_category: Optional[str] = ...,
        limit: int = ...,
    ) -> List[Tuple[str, float]]: ...

    async def vector_search(
        self,
        *,
        query: str,
        summary_type: Optional[str] = ...,
        summary_category: Optional[str] = ...,
        limit: int = ...,
    ) -> List[Dict[str, Any]]: ...

    async def keyword_search(
        self,
        *,
        query: str,
        summary_type: Optional[str] = ...,
        summary_category: Optional[str] = ...,
        limit: int = ...,
    ) -> List[str]: ...

    async def fetch_by_ids(
        self,
        summary_ids: List[str],
        *,
        summary_type: Optional[str] = ...,
        summary_category: Optional[str] = ...,
    ) -> List[Dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# L4 procedural memory store
# ---------------------------------------------------------------------------


@runtime_checkable
class L4StoreProtocol(Protocol):
    """Interface expected by :class:`L4Handler` from the L4 procedural memory store."""

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = ...,
    ) -> List[Tuple[str, float]]: ...

    async def keyword_search(
        self,
        query: str,
        *,
        limit: int = ...,
    ) -> List[str]: ...

    async def fetch_by_ids(
        self,
        skill_ids: List[str],
    ) -> List[Dict[str, Any]]: ...
