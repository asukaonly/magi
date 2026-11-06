"""Read and semantic-ranking service for the canonical L1 event owner."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Dict, List, Literal, Optional, cast

from ...event_contracts import MemoryDomain, MemoryEvent
from ..ports import EventQuery, EventEvidenceReference, EventSourceIdentity
from ..overview_contracts import EventOverview, EventOverviewQuery
from .common import L1EventQueryHostProtocol
from .idempotency import L1EventIdempotencyMixin
from .maintenance import L1EventMaintenanceQueryMixin
from .timeline import L1TimelineQueryMixin


class L1EventQueryMixin(
    L1EventIdempotencyMixin, L1EventMaintenanceQueryMixin, L1TimelineQueryMixin,
):
    """Apply memory-facing presentation and ranking to repository results."""

    async def search_events(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        domain_filters: Optional[List[str]] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search L1 events using the vector index and keyword matching."""
        host = cast(L1EventQueryHostProtocol, self)
        semantic_hits = await host._semantic_search_event_hits(
            query=query, limit=max(limit * 5, 20)
        )
        if semantic_hits:
            ranked_events = await host._fetch_ranked_events(
                hits=semantic_hits,
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                source_filters=source_filters,
                domain_filters=domain_filters,
                l1_retrieval_scopes=l1_retrieval_scopes,
                limit=limit,
            )
            if ranked_events:
                return ranked_events

        events = await self.query_events(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            source_filters=source_filters,
            l1_retrieval_scopes=l1_retrieval_scopes,
            limit=max(limit * 5, 20),
        )
        allowed_domains = {MemoryDomain.from_value(value).label for value in domain_filters or []}
        query_tokens = [token for token in query.lower().split() if token]
        filtered = [
            event
            for event in events
            if event["memory_domain"] != MemoryDomain.RUNTIME_TELEMETRY.label
            and (not allowed_domains or event["memory_domain"] in allowed_domains)
            and all(token in event["content"].lower() for token in query_tokens)
        ]
        return filtered[:limit]


    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single event by id, including a soft-deleted event.

        This raw reader exists for deletion retries and maintenance workflows.
        Product-facing callers must use :meth:`get_user_visible_event`.
        """
        return await self._get_event_by_id(event_id)


    async def get_active_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single event only while it has not been soft-deleted."""
        return await self._get_event_by_id(event_id, active_only=True)


    async def get_user_visible_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch an active event that is allowed on user-facing surfaces."""
        return await self._get_event_by_id(
            event_id,
            active_only=True,
            user_visible_only=True,
        )


    async def _get_event_by_id(
        self,
        event_id: str,
        *,
        active_only: bool = False,
        user_visible_only: bool = False,
    ) -> Optional[Dict[str, Any]]:
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        try:
            active_embedding_profile_id, _ = host._resolve_active_embedding_profile_id()
        except Exception:
            active_embedding_profile_id = None
        record = await host.event_repository.get(
            event_id,
            visibility="user_visible" if user_visible_only else "active" if active_only else "raw",
        )
        return (
            host._record_to_dict(record, active_embedding_profile_id=active_embedding_profile_id)
            if record is not None else None
        )


    async def get_memory_event(self, event_id: str) -> Optional[MemoryEvent]:
        """Fetch a single event as the canonical MemoryEvent contract."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        record = await host.event_repository.get(event_id)
        return host._record_to_memory_event(record) if record is not None else None


    async def get_event_timestamps(self, event_ids: List[str]) -> Dict[str, float]:
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        return await host.event_repository.get_event_timestamps(event_ids)

    async def get_evidence_records(self, event_ids: List[str]) -> dict[str, EventEvidenceReference]:
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        return await host.event_repository.get_evidence_records(event_ids)

    async def get_raw_event_turn_ids(self, event_ids: List[str]) -> Dict[str, str]:
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        return await host.event_repository.get_raw_event_turn_ids(event_ids)

    async def get_raw_event_source_identities(
        self,
        event_ids: List[str],
    ) -> dict[str, EventSourceIdentity]:
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        return await host.event_repository.get_raw_event_source_identities(event_ids)

    async def get_raw_event_active_states(
        self,
        event_ids: List[str],
    ) -> Dict[str, bool]:
        """Return visibility-at-read for raw rows, including soft-deleted events."""
        identities = await self.get_raw_event_source_identities(event_ids)
        return {
            event_id: bool(identity.get("was_active"))
            for event_id, identity in identities.items()
        }


    async def get_event_vectors(
        self,
        event_ids: List[str],
    ) -> Dict[str, List[float]]:
        """Return embedding vectors for the given event IDs.

        For each event, returns the chunk-0 embedding (primary chunk).
        Events without embeddings are silently omitted.
        """
        host = cast(L1EventQueryHostProtocol, self)
        if not event_ids or host._vector_index is None:
            return {}
        try:
            active_profile_id, _ = host._resolve_active_embedding_profile_id()
        except Exception:
            return {}
        if active_profile_id is None:
            return {}
        chunk_ids = [host._chunk_id_for_event(eid, 0) for eid in event_ids]
        raw = await host._vector_index.get_vectors(
            entity_ids=chunk_ids,
            model_key=active_profile_id,
        )
        result: Dict[str, List[float]] = {}
        for eid in event_ids:
            cid = host._chunk_id_for_event(eid, 0)
            if cid in raw:
                result[eid] = raw[cid]
        return result


    async def fetch_events(
        self,
        event_ids: List[str],
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        source_filters: Optional[List[str]] = None,
        domain_filters: Optional[List[str]] = None,
        exclude_domain: Optional[str] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Hydrate filtered events in caller order through their storage owner."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        records = await host.event_repository.fetch_events(
            event_ids, session_id=session_id, user_id=user_id, event_types=event_types,
            source_filters=source_filters, domain_filters=domain_filters,
            exclude_domain=exclude_domain, time_start=time_start, time_end=time_end,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        return [host._record_to_dict(record) for record in records]

    async def list_events(
        self, *, limit: int = 100, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List the newest events, optionally constrained by event type."""
        return await self.query_events(event_type=event_type, limit=limit)


    async def read_event_overview(self, query: EventOverviewQuery) -> EventOverview:
        """Read counts and bounded previews without loading raw event payloads."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        return await host.event_repository.read_event_overview(query)

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
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        order_by: Literal[
            "timestamp_desc", "timestamp_asc", "importance_desc", "created_at_desc"
        ] = "timestamp_desc",
    ) -> List[Dict[str, Any]]:
        """Query filtered events without exposing driver values to callers."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        values = locals()
        query_spec = EventQuery(**{field.name: values[field.name] for field in fields(EventQuery)})
        records = await host.event_repository.query_events(query_spec)
        active_profile = host._resolve_active_embedding_profile_id()[0] if include_embedding_fields else None
        return [host._record_to_dict(
            record, include_embedding_fields=include_embedding_fields,
            active_embedding_profile_id=active_profile,
        ) for record in records]

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
    ) -> List[Dict[str, Any]]:
        """Read a bounded window in the owning session's sequence order."""
        host = cast(L1EventQueryHostProtocol, self)
        await host.initialize()
        records = await host.event_repository.query_session_event_window(
            session_id=session_id, center_session_seq=center_session_seq, window=window,
            user_id=user_id, limit=limit, include_metadata_json=include_metadata_json,
        )
        active_profile = host._resolve_active_embedding_profile_id()[0] if include_embedding_fields else None
        return [host._record_to_dict(
            record, include_embedding_fields=include_embedding_fields,
            active_embedding_profile_id=active_profile,
        ) for record in records]
