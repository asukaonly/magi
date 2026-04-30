"""Risk classifier result models."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import RiskLevel


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


__all__ = ["ClassificationResult", "RiskSignal"]
