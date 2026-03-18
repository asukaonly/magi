"""Context bundle contracts used by L2 reference resolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ContextEntity:
    """Time-bounded contextual entity candidate."""

    context_id: str
    kind: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_event_ids: list[str] = field(default_factory=list)
    created_at: float = 0.0
    expires_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResolvedContextRef:
    """Resolved direct or contextual reference used by extraction."""

    surface: str
    reference_type: str
    resolved_ref: str
    resolved_kind: str
    confidence: float
    evidence_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextBundle:
    """Collected contextual candidates for one extraction event."""

    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    recent_entities: list[dict[str, Any]] = field(default_factory=list)
    live_context_entities: list[ContextEntity] = field(default_factory=list)
    pronoun_bindings: list[dict[str, Any]] = field(default_factory=list)
    source_event_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["live_context_entities"] = [item.to_dict() for item in self.live_context_entities]
        return payload


__all__ = [
    "ContextBundle",
    "ContextEntity",
    "ResolvedContextRef",
]
