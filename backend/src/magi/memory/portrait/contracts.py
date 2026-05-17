"""Dataclass contracts for the persona portrait rail."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ObservationKind = Literal["reflection", "assertion", "relationship", "procedure"]
MemoryLayer = Literal["L2", "L3", "L4"]


@dataclass
class PortraitObservation:
    """One persona-voiced observation derived from raw memory."""

    kind: ObservationKind
    text: str
    basis_count: int
    basis_summary: str
    basis_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "basis_count": self.basis_count,
            "basis_summary": self.basis_summary,
            "basis_refs": list(self.basis_refs),
        }


@dataclass
class PortraitPayload:
    """Response payload returned by /api/memory/portrait."""

    session_id: str
    persona_id: str
    topic: str
    generated_at: int  # unix seconds
    observations: list[PortraitObservation] = field(default_factory=list)
    is_cold_start: bool = False
    cold_start_line: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "persona_id": self.persona_id,
            "topic": self.topic,
            "generated_at": self.generated_at,
            "observations": [o.to_dict() for o in self.observations],
            "is_cold_start": self.is_cold_start,
            "cold_start_line": self.cold_start_line,
        }


@dataclass
class TopicResult:
    """Output of TopicExtractor."""

    topic: str
    entities: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.topic.strip() and not self.entities


@dataclass
class RawMemorySnippet:
    """A raw L2/L3/L4 memory fragment passed to the persona-lens renderer."""

    id: str
    kind: ObservationKind
    layer: MemoryLayer
    statement: str
    confidence: float | None = None
    occurred_at: float | None = None
