"""Portable persistence values and deterministic row normalization."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal, TypedDict
from .events import MemoryEvent
from .evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope
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
