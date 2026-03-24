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
