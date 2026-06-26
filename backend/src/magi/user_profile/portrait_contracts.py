"""Contracts for the product-facing self portrait."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


UserPortraitObservationKind = Literal["reflection", "assertion", "relationship", "procedure"]


@dataclass
class UserPortraitObservation:
    """One evidence-backed item used to build the self portrait view."""

    kind: UserPortraitObservationKind
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
class UserPortraitPayload:
    """Response payload returned by the product-facing self portrait."""

    session_id: str
    persona_id: str
    topic: str
    generated_at: int
    observations: list[UserPortraitObservation] = field(default_factory=list)
    is_cold_start: bool = False
    cold_start_line: str | None = None
    cold_start_reason: str | None = None
    is_stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "persona_id": self.persona_id,
            "topic": self.topic,
            "generated_at": self.generated_at,
            "observations": [o.to_dict() for o in self.observations],
            "is_cold_start": self.is_cold_start,
            "cold_start_line": self.cold_start_line,
            "cold_start_reason": self.cold_start_reason,
            "is_stale": self.is_stale,
        }


__all__ = [
    "UserPortraitObservation",
    "UserPortraitObservationKind",
    "UserPortraitPayload",
]
