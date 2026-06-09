"""Permission classification types promoted to the SDK layer.

These types were originally defined in magi.agent.control.permission.
Promoting them here allows plugin tools and the SDK to depend on them
without importing host internals.

The host modules (contracts.py, classifier_models.py) re-export these
symbols so existing host code continues to work and identity is preserved
(``host.RiskLevel is sdk.RiskLevel`` holds).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    """Risk tier assigned to ``(tool, args)`` by the classifier.

    Ordering matters: comparisons use the integer ``order`` attribute
    to avoid string-compare surprises (``"destructive" < "high"`` would
    be wrong lexicographically).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"
    KILL_LISTED = "kill_listed"

    @property
    def order(self) -> int:
        return _RISK_ORDER[self]

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, RiskLevel):
            return self.order >= other.order
        return NotImplemented

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, RiskLevel):
            return self.order > other.order
        return NotImplemented

    def __le__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, RiskLevel):
            return self.order <= other.order
        return NotImplemented

    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, RiskLevel):
            return self.order < other.order
        return NotImplemented


_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.DESTRUCTIVE: 3,
    RiskLevel.KILL_LISTED: 4,
}


@dataclass(slots=True, frozen=True)
class RiskSignal:
    """Named signal contributing to the risk tier."""

    key: str
    description: str


@dataclass(slots=True)
class ClassificationResult:
    level: RiskLevel
    signals: list[RiskSignal]
    preview: str | None = None


__all__ = ["RiskLevel", "RiskSignal", "ClassificationResult"]
