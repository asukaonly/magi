"""Completion policy contracts for unified agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CompletionPolicy:
    """Immutable bounds used by the completion gate."""

    max_repair_iterations: int = 2
    require_local_write_validation: bool = True
    require_unknown_effect_validation: bool = True
    require_effect_terminal_state: bool = True
    validation_tool_names: frozenset[str] = field(
        default_factory=lambda: frozenset({"verify"})
    )

    def __post_init__(self) -> None:
        if self.max_repair_iterations < 0:
            raise ValueError("max_repair_iterations must not be negative")


__all__ = ["CompletionPolicy"]
