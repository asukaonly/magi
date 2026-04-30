"""Domain types for the personality emotional state engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MoodType(Enum):
    """Emotion type."""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    EXCITED = "excited"
    SATISFIED = "satisfied"
    CURIOUS = "curious"
    TIRED = "tired"
    STRESSED = "stressed"
    CONFUSED = "confused"
    FOCUSED = "focused"
    PLAYFUL = "playful"


class InteractionOutcome(Enum):
    """Interaction result type."""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial"
    FAILURE = "failure"
    REJECTED = "rejected"
    ERROR = "error"
    TIMEOUT = "timeout"


class EngagementLevel(Enum):
    """User engagement level."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class EmotionalConfig:
    """Configuration parameters for emotional state evolution."""
    energy_decay_rate: float = 0.01
    stress_growth_rate: float = 0.1
    stress_recovery_rate: float = 0.05
    mood_fluctuation: float = 0.1
    social_decay_rate: float = 0.02
    recovery_threshold: float = 0.8
    recovery_speed: float = 0.2


@dataclass
class EmotionalEvent:
    """Emotional event record."""
    timestamp: float
    event_type: str
    previous_mood: str
    new_mood: str
    mood_delta: float
    energy_delta: float
    stress_delta: float
    cause: str


__all__ = [
    "EngagementLevel",
    "EmotionalConfig",
    "EmotionalEvent",
    "InteractionOutcome",
    "MoodType",
]