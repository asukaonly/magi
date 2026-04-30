"""Behavior evolution data models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SatisfactionLevel(Enum):
    """User satisfaction level."""

    VERY_LOW = "very_low"
    LOW = "low"
    NEUTRAL = "neutral"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class TaskInteractionRecord:
    """Task interaction record."""

    task_id: str
    task_category: str
    timestamp: float
    clarification_count: int
    confirmation_count: int
    correction_count: int
    satisfaction: SatisfactionLevel
    task_complexity: float
    task_duration: float
    accepted: bool


@dataclass
class CategoryStatistics:
    """Aggregate behavior statistics for a task category."""

    category: str
    total_tasks: int = 0
    accepted_tasks: int = 0
    avg_clarifications: float = 0.0
    avg_confirmations: float = 0.0
    avg_corrections: float = 0.0
    avg_satisfaction: float = 0.0
    avg_complexity: float = 0.0
    cautious_score: float = 0.5
    impatient_score: float = 0.5
    dense_score: float = 0.5


__all__ = ["CategoryStatistics", "SatisfactionLevel", "TaskInteractionRecord"]
