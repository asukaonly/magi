"""Rules-first interruption classification for chat task-agent runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InterruptionDisposition(str, Enum):
    """How a new user turn should affect the active run."""

    INTERRUPT = "interrupt"
    AUGMENT = "augment"
    DEFER = "defer"


@dataclass(slots=True)
class StepState:
    """Execution-step constraints that affect interruption handling."""

    atomic: bool = False
    side_effecting: bool = False


@dataclass(slots=True)
class InterruptionContext:
    """Input to the interruption classifier."""

    user_text: str
    step_state: StepState = field(default_factory=StepState)


class InterruptionClassifier:
    """Classify how a newly arrived user turn should affect the active run."""

    _INTERRUPT_PATTERNS = (
        "stop",
        "cancel",
        "abort",
        "change the goal",
        "change goal",
        "new goal",
        "new plan",
        "instead",
        "switch to",
        "don't do that",
        "dont do that",
        "never mind",
    )
    _AUGMENT_PATTERNS = (
        "also",
        "additionally",
        "by the way",
        "for context",
        "one more thing",
        "more context",
        "more detail",
        "in addition",
    )

    def classify(self, context: InterruptionContext) -> InterruptionDisposition:
        """Return the disposition for the new user turn."""
        if context.step_state.atomic or context.step_state.side_effecting:
            return InterruptionDisposition.DEFER
        if self._looks_like_interrupt(context.user_text):
            return InterruptionDisposition.INTERRUPT
        if self._looks_like_augment(context.user_text):
            return InterruptionDisposition.AUGMENT
        return InterruptionDisposition.DEFER

    def _looks_like_interrupt(self, user_text: str) -> bool:
        normalized_text = user_text.lower()
        return any(pattern in normalized_text for pattern in self._INTERRUPT_PATTERNS)

    def _looks_like_augment(self, user_text: str) -> bool:
        normalized_text = user_text.lower()
        return any(pattern in normalized_text for pattern in self._AUGMENT_PATTERNS)
