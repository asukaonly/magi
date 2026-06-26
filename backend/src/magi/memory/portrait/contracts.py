"""Neutral contracts for memory snippets used by portrait-like surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


ObservationKind = Literal["reflection", "assertion", "relationship", "procedure"]
MemoryLayer = Literal["L2", "L3", "L4"]


class MemorySnippetQuery(Protocol):
    """Topic-like query consumed by the memory snippet fetcher."""

    topic: str
    entities: list[str]

    def is_empty(self) -> bool: ...


@dataclass
class RawMemorySnippet:
    """A raw L2/L3/L4 memory fragment returned by memory retrieval."""

    id: str
    kind: ObservationKind
    layer: MemoryLayer
    statement: str
    confidence: float | None = None
    occurred_at: float | None = None
