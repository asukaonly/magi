"""Memory-facing maintenance queries through the event repository."""

from __future__ import annotations
from typing import Any, Dict, List, Optional, cast
from .common import L1EventQueryHostProtocol


class L1EventMaintenanceQueryMixin:
    async def summarize_event_sources(
        self,
        *,
        source_filters: Optional[List[str]] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        return await host.event_repository.summarize_event_sources(source_filters=source_filters, cognition_eligible=cognition_eligible, start_time=start_time, end_time=end_time, exclude_memory_domain=exclude_memory_domain, exclude_retention_class=exclude_retention_class)

    async def count_events(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_id: Optional[str] = None,
        event_type: Optional[str] = None,
        exclude_event_types: Optional[List[str]] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> int:
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        return await host.event_repository.count_events(session_id=session_id, user_id=user_id, event_id=event_id, event_type=event_type, exclude_event_types=exclude_event_types, query=query, source_filters=source_filters, source_item_id=source_item_id, idempotency_key=idempotency_key, start_time=start_time, end_time=end_time, l1_retrieval_scopes=l1_retrieval_scopes)

    async def list_compressible_event_page(
        self,
        *,
        older_than: float,
        limit: int = 1000,
        after: tuple[float, str] | None = None,
    ) -> list[tuple[float, str]]:
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_compressible_event_page(older_than=older_than, limit=limit, after=after)
