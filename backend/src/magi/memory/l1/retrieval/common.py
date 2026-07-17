"""Shared protocol and constants for L1 event retrieval mixins."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

import aiosqlite

from ...event_contracts import MemoryEvent

FACT_EVENTS_TABLE = "fact_events"


class L1EventQueryHostProtocol(Protocol):
    db_path: str
    _vector_index: Any

    async def initialize(self) -> None: ...

    def _row_to_dict(
        self,
        row: aiosqlite.Row,
        *,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        active_embedding_profile_id: str | None = None,
    ) -> Dict[str, Any]: ...

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent: ...

    async def _semantic_search_event_hits(
        self, *, query: str, limit: int, user_id: str | None = None
    ) -> list[Any]: ...

    async def _fetch_ranked_events(
        self,
        *,
        hits: list[Any],
        session_id: Optional[str],
        user_id: Optional[str],
        event_type: Optional[str],
        source_filters: Optional[List[str]],
        domain_filters: Optional[List[str]],
        l1_retrieval_scopes: Optional[List[str]],
        limit: int,
    ) -> List[Dict[str, Any]]: ...

    def _chunk_id_for_event(self, event_id: str, chunk_index: int) -> str: ...

    def _resolve_active_embedding_profile_id(self) -> tuple[str | None, dict[str, Any]]: ...

    def _to_timeline_view(self, event: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]: ...

    def _build_event_filters(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_domain: Optional[str] = None,
        event_id: Optional[str] = None,
        event_type: Optional[str] = None,
        exclude_event_types: Optional[List[str]] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> tuple[str, List[Any]]: ...

    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]: ...

    async def get_active_event(self, event_id: str) -> Optional[Dict[str, Any]]: ...

    async def get_user_visible_event(self, event_id: str) -> Optional[Dict[str, Any]]: ...

    async def get_raw_event_turn_ids(self, event_ids: List[str]) -> Dict[str, str]: ...

    async def get_raw_event_source_identities(
        self,
        event_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]: ...

    async def get_raw_event_active_states(
        self,
        event_ids: List[str],
    ) -> Dict[str, bool]: ...

    async def query_events(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_domain: Optional[str] = None,
        event_id: Optional[str] = None,
        event_type: Optional[str] = None,
        exclude_event_types: Optional[List[str]] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order: str = "desc",
        order_by: str = "timestamp_desc",
        include_embedding: bool = False,
        include_metadata_json: bool = True,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]: ...

    async def query_session_event_window(
        self,
        *,
        session_id: str,
        center_session_seq: int,
        window: int,
        user_id: Optional[str] = None,
        limit: int | None = None,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
    ) -> List[Dict[str, Any]]: ...


__all__ = ["FACT_EVENTS_TABLE", "L1EventQueryHostProtocol"]
