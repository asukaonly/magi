"""Storage-neutral maintenance scans and conditional evidence updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ports import EventEvidence, MemoryEventRecord


@dataclass(frozen=True, slots=True)
class EvidenceBackfillQuery:
    user_id: str | None = None
    source_filters: tuple[str, ...] = ()
    event_type: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    stale_rule_version: int | None = None


@dataclass(frozen=True, slots=True)
class EventScanItem:
    sequence: int
    event_id: str
    record: MemoryEventRecord | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceAnnotationUpdate:
    expected: MemoryEventRecord
    evidence: EventEvidence


@dataclass(frozen=True, slots=True)
class EventClearState:
    entity_link_generation: int
    has_projected_links: bool
