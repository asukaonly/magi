"""Contracts for prompt-facing L0 projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class L0PromptWorkbenchProjection:
    """Prompt-facing L0 workbench payload."""

    session: dict[str, Any] | None
    goal_stack: list[Any] = field(default_factory=list)
    active_entities: list[Any] = field(default_factory=list)
    temporary_tactics: list[Any] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable payload for retrieval and prompt assembly."""
        return asdict(self)

    def to_retrieval_entry(self) -> dict[str, Any]:
        """Return the retrieval-facing L0 workbench entry shape."""
        payload = self.to_payload()
        return {
            "session": payload.get("session"),
            "goals": payload.get("goal_stack", []),
            "active_entities": payload.get("active_entities", []),
            "temporary_tactics": payload.get("temporary_tactics", []),
        }
