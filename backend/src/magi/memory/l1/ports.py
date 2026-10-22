"""Storage-neutral commands for the atomic L1 event boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

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
