"""Personality layer data models."""

import time
from typing import Dict, List
from enum import Enum
from dataclasses import dataclass, field


class AmbiguityTolerance(Enum):
    """Ambiguity tolerance"""
    IMPATIENT = "impatient"
    CAUTIOUS = "cautious"
    ADAPTIVE = "adaptive"


@dataclass
class TaskBehaviorProfile:
    """Behavior preference layer"""
    task_category: str
    information_density: str = "medium"
    ambiguity_tolerance: AmbiguityTolerance = AmbiguityTolerance.ADAPTIVE
    response_prefers: List[str] = field(default_factory=list)
    response_avoids: List[str] = field(default_factory=list)
    error_tolerance: float = 0.5
    proactivity: str = "reactive"


@dataclass
class EmotionalState:
    """Emotional state layer"""
    current_mood: str = "neutral"
    mood_intensity: float = 0.5
    energy_level: float = 0.7
    stress_level: float = 0.2
    focus_state: str = "normal"
    social_state: str = "neutral"
    active_stp_trigger: str = ""
    active_stp_state_name: str = ""
    stp_idle_rounds: int = 0
    updated_at: float = field(default_factory=time.time)
