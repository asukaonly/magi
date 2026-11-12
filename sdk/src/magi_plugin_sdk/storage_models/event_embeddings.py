"""Portable persistence values and deterministic row normalization."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, TypedDict
from .chunks import ChunkedText
from .embedding_profile import EmbeddingProfile
from .event_text import build_l1_embedding_text
from .events import MemoryDomain, MemoryEvent


@dataclass(frozen=True, slots=True)
class EventEmbeddingSource:
    """Immutable source identity checked again within publication transactions."""

    event_id: str
    event_type: str
    source: str
    user_id: str | None
    memory_domain: MemoryDomain
    text: str

    @classmethod
    def from_event(cls, event: MemoryEvent) -> EventEmbeddingSource:
        return cls(
            event.event_id, event.event_type, event.source, event.user_id,
            event.memory_domain, build_l1_embedding_text(event),
        )


@dataclass(frozen=True, slots=True)
class EventEmbeddingPublication:
    source: EventEmbeddingSource
    status: Literal["ready", "failed"]
    profile_id: str | None
    profile: EmbeddingProfile | None = None
    chunks: tuple[ChunkedText, ...] = ()
    embedded_at: float | None = None


class EventChunkRecord(TypedDict):
    chunk_id: str
    event_id: str
    chunk_index: int
    chunk_text: str
    char_start: int
    char_end: int
