"""Evidence-driven reasoning policy for unified agent steps."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ...config.models import ThinkingDepth


class ReasoningPreference(str, Enum):
    """Product-level user preference, independent of provider dialects."""

    AUTO = "auto"
    FAST = "fast"
    DEEP = "deep"


@dataclass(frozen=True, slots=True)
class ReasoningPolicy:
    """Immutable bounds for one parent run."""

    preference: ReasoningPreference = ReasoningPreference.AUTO
    initial_depth: ThinkingDepth = ThinkingDepth.LOW
    maximum_depth: ThinkingDepth = ThinkingDepth.HIGH
    max_escalations: int = 2

    @classmethod
    def from_preference(cls, preference: ReasoningPreference) -> "ReasoningPolicy":
        if preference is ReasoningPreference.FAST:
            return cls(
                preference=preference,
                initial_depth=ThinkingDepth.NONE,
                maximum_depth=ThinkingDepth.LOW,
                max_escalations=1,
            )
        if preference is ReasoningPreference.DEEP:
            return cls(
                preference=preference,
                initial_depth=ThinkingDepth.MEDIUM,
                maximum_depth=ThinkingDepth.MAX,
                max_escalations=2,
            )
        return cls(preference=preference)

    def to_dict(self) -> dict[str, object]:
        return {
            "preference": self.preference.value,
            "initial_depth": self.initial_depth.value,
            "maximum_depth": self.maximum_depth.value,
            "max_escalations": self.max_escalations,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReasoningPolicy":
        return cls(
            preference=ReasoningPreference(str(value["preference"])),
            initial_depth=ThinkingDepth(str(value["initial_depth"])),
            maximum_depth=ThinkingDepth(str(value["maximum_depth"])),
            max_escalations=int(value["max_escalations"]),
        )


@dataclass(slots=True)
class ReasoningState:
    """Monotonic reasoning state persisted with a run checkpoint."""

    requested_depth: ThinkingDepth
    effective_depth: ThinkingDepth
    escalation_count: int = 0
    last_reason: str = "initial_policy"

    @classmethod
    def start(cls, policy: ReasoningPolicy) -> "ReasoningState":
        return cls(
            requested_depth=policy.initial_depth,
            effective_depth=policy.initial_depth,
        )

    def escalate(self, policy: ReasoningPolicy, *, reason: str) -> bool:
        if self.escalation_count >= policy.max_escalations:
            return False
        next_depth = _next_depth(self.requested_depth)
        if _rank(next_depth) > _rank(policy.maximum_depth):
            return False
        if next_depth is self.requested_depth:
            return False
        self.requested_depth = next_depth
        self.effective_depth = next_depth
        self.escalation_count += 1
        self.last_reason = reason
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_depth": self.requested_depth.value,
            "effective_depth": self.effective_depth.value,
            "escalation_count": self.escalation_count,
            "last_reason": self.last_reason,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReasoningState":
        return cls(
            requested_depth=ThinkingDepth(str(value["requested_depth"])),
            effective_depth=ThinkingDepth(str(value["effective_depth"])),
            escalation_count=int(value["escalation_count"]),
            last_reason=str(value["last_reason"]),
        )


_DEPTHS = (
    ThinkingDepth.NONE,
    ThinkingDepth.LOW,
    ThinkingDepth.MEDIUM,
    ThinkingDepth.HIGH,
    ThinkingDepth.MAX,
)


def _rank(depth: ThinkingDepth) -> int:
    return _DEPTHS.index(depth)


def _next_depth(depth: ThinkingDepth) -> ThinkingDepth:
    return _DEPTHS[min(_rank(depth) + 1, len(_DEPTHS) - 1)]


__all__ = ["ReasoningPolicy", "ReasoningPreference", "ReasoningState"]
