"""Contracts for prompt-facing L0 projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class L0ExecutionSummary:
    """Prompt-safe summary of the current execution lane."""

    active_run_summary: str
    awaiting_external_result: bool
    latest_user_augmentation_summary: str | None = None


@dataclass(slots=True)
class L0PromptWorkbenchProjection:
    """Prompt-facing L0 workbench payload with summarized execution state."""

    session: dict[str, Any] | None
    goal_stack: list[Any] = field(default_factory=list)
    active_entities: list[Any] = field(default_factory=list)
    temporary_tactics: list[Any] = field(default_factory=list)
    execution_summary: L0ExecutionSummary | None = None

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable payload for retrieval and prompt assembly."""
        return asdict(self)

    def to_retrieval_entry(self) -> dict[str, Any]:
        """Return the retrieval-facing L0 workbench entry shape."""
        payload = self.to_payload()
        return {
            "session": payload.get("session"),
            "goals": payload.get("goal_stack", [])[:3],
            "active_entities": payload.get("active_entities", [])[:5],
            "temporary_tactics": payload.get("temporary_tactics", [])[:5],
            "execution_summary": payload.get("execution_summary"),
        }
