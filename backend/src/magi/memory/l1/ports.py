"""Storage-neutral commands for the atomic L1 event boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, List, Dict, Optional, TypedDict

from ..event_contracts import MemoryEvent
from ..evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope

if TYPE_CHECKING:
    from .source_facets import SourceFacet


@dataclass(frozen=True, slots=True)
class EventEvidence:
    status: EvidenceStatus
    classification: EvidenceClass
    rule_version: int
    retrieval_scope: L1RetrievalScope


@dataclass(frozen=True, slots=True)
class EventAppend:
    """One event and its derived rows, committed in the same transaction."""

    event: MemoryEvent
    evidence: EventEvidence
    metadata: dict[str, Any] | None
    embedding_status: str
    embedding_profile_id: str | None
    search_text: str
    source_facets: tuple[SourceFacet, ...]


@dataclass(frozen=True, slots=True)
class EventAppendResult:
    event_id: str
    inserted: bool
    session_seq: int | None


@dataclass(frozen=True, slots=True)
class EventDeletionPlan:
    event_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]


EventVisibility = Literal["raw", "active", "user_visible"]


@dataclass(frozen=True, slots=True)
class MemoryEventRecord:
    event: MemoryEvent
    evidence: EventEvidence
    embedding_chunk_count: int
    last_embedded_at: float | None
    deleted_at: float | None


@dataclass(frozen=True, slots=True)
class EventQuery:
    session_id: str | None = None
    user_id: str | None = None
    memory_domain: str | None = None
    event_id: str | None = None
    event_type: str | None = None
    exclude_event_types: list[str] | None = None
    query: str | None = None
    source_filters: list[str] | None = None
    source_item_id: str | None = None
    idempotency_key: str | None = None
    cognition_eligible: bool | None = None
    start_time: float | None = None
    end_time: float | None = None
    exclude_memory_domain: str | None = None
    exclude_retention_class: str | None = None
    l1_retrieval_scopes: list[str] | None = None
    limit: int = 100
    offset: int = 0
    include_metadata_json: bool = True
    order_by: Literal["timestamp_desc", "timestamp_asc", "importance_desc", "created_at_desc"] = "timestamp_desc"


class EventEvidenceReference(TypedDict):
    event_id: str
    timestamp: float
    source: str
    source_item_id: str | None
    content: str
    author_type: str
    event_type: str
    metadata_json: dict[str, Any]


class EventSourceIdentity(TypedDict):
    event_type: str | None
    source: str | None
    source_item_id: str | None
    idempotency_key: str | None
    turn_id: str | None
    session_id: str | None
    user_id: str | None
    was_active: bool


class MemoryEventRepository(Protocol):
    async def append(self, command: EventAppend) -> EventAppendResult:
        """Atomically deduplicate, allocate sequence, and persist all side rows."""
        ...

    async def find_by_idempotency(
        self, *, source: str, event_type: str, idempotency_key: str,
    ) -> str | None: ...

    async def get(
        self, event_id: str, *, visibility: EventVisibility = "raw",
    ) -> MemoryEventRecord | None: ...

    async def query_events(self, query: EventQuery) -> list[MemoryEventRecord]: ...

    async def get_event_timestamps(self, event_ids: list[str]) -> dict[str, float]: ...

    async def get_evidence_records(self, event_ids: list[str]) -> dict[str, EventEvidenceReference]: ...

    async def get_raw_event_turn_ids(self, event_ids: list[str]) -> dict[str, str]: ...

    async def get_raw_event_source_identities(self, event_ids: list[str]) -> dict[str, EventSourceIdentity]: ...

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
    ) -> list[MemoryEventRecord]: ...

    async def query_session_event_window(
        self,
        *,
        session_id: str,
        center_session_seq: int,
        window: int,
        user_id: Optional[str] = None,
        limit: int | None = None,
        include_metadata_json: bool = True,
    ) -> list[MemoryEventRecord]: ...

    async def summarize_event_sources(
        self,
        *,
        source_filters: Optional[List[str]] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
    ) -> List[Dict[str, Any]]: ...

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
    ) -> int: ...

    async def list_compressible_event_page(
        self,
        *,
        older_than: float,
        limit: int = 1000,
        after: tuple[float, str] | None = None,
    ) -> list[tuple[float, str]]: ...

    async def list_source_facets(
        self,
        *,
        event_id: str | None = None,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str] | None = None,
        normalized_text_values: list[str] | None = None,
        limit: int = 1000,
    ) -> list[SourceFacet]: ...

    async def count_source_facets(
        self,
        *,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str] | None = None,
    ) -> int: ...

    async def find_events_by_source_facets(
        self,
        *,
        source: str | None = None,
        sources: list[str] | None = None,
        facet_names: list[str],
        normalized_text_values: list[str],
        user_id: str | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        limit: int = 1000,
    ) -> list[MemoryEventRecord]: ...

    async def rebuild_source_facets(
        self,
        *,
        source_filter: str | None = None,
        batch_size: int = 500,
        limit: int | None = None,
    ) -> dict[str, int]: ...

    async def prepare_event_deletion(
        self, event_ids: list[str], *, only_deleted: bool = False,
    ) -> EventDeletionPlan: ...

    async def soft_delete_events(self, event_ids: list[str], *, deleted_at: float) -> int: ...

    async def purge_deleted_events(self, event_ids: list[str]) -> int: ...

    async def list_active_event_ids_by_entity(
        self,
        entity_id: str,
        *,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]: ...

    async def list_raw_event_ids_by_entity(
        self,
        entity_id: str,
        *,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]: ...

    async def list_active_event_ids_by_time_range(
        self,
        *,
        start: float,
        end: float,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]: ...

    async def list_raw_event_ids_by_time_range(
        self,
        *,
        start: float,
        end: float,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]: ...

    async def list_active_event_ids_by_chat_sources(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        turn_ids: list[str] | tuple[str, ...] = (),
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]: ...

    async def list_raw_event_ids_by_chat_sources(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        turn_ids: list[str] | tuple[str, ...] = (),
        message_ids: list[str] | tuple[str, ...] = (),
        include_session: bool = True,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]: ...

    async def list_active_event_ids_by_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]: ...

    async def list_raw_event_ids_by_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]: ...

    async def get_pinned_payloads(self, event_ids: list[str]) -> dict[str, str]: ...

    async def prune_pinned_payloads(self, *, retention_seconds: float, now: float) -> int: ...

    async def list_ready_cognition_handoffs(self, *, now: float, limit: int = 100) -> list[str]: ...

    async def complete_cognition_handoff(self, event_id: str) -> None: ...

    async def retry_cognition_handoff(self, event_id: str, *, error: str, now: float) -> None: ...
