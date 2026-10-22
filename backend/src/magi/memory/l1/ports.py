"""Storage-neutral commands for the atomic L1 event boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, List, Optional, TypedDict

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
