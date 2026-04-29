"""Domain models for personality growth memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class MilestoneType(Enum):
    """Milestone type."""
    FIRST_USE = "first_use"
    STREAK = "streak"
    MASTERY = "mastery"
    RELATIONSHIP = "relationship"
    ACHIEVEMENT = "achievement"
    PERSONALITY_CHANGE = "personality"
    SPECIAL = "special"
    BOOTSTRAP_STARTED = "bootstrap_started"
    BOOTSTRAP_COMPLETED = "bootstrap_completed"
    BOOTSTRAP_ROUND = "bootstrap_round"
    JOURNAL_ENTRY = "journal_entry"


class InteractionType(Enum):
    """Interaction type."""
    CHAT = "chat"
    TASK = "task"
    CODE = "code"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    LEARNING = "learning"


@dataclass
class Milestone:
    """Growth milestone."""
    id: str
    type: MilestoneType
    title: str
    description: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationshipProfile:
    """Relationship profile."""
    user_id: str
    depth: float
    first_interaction: float
    last_interaction: float
    total_interactions: int
    interaction_types: Dict[str, int]
    sentiment_score: float
    trust_level: float
    notes: List[str] = field(default_factory=list)


@dataclass
class PersonalityEvolution:
    """Personality evolution record."""
    timestamp: float
    aspect: str
    previous_value: Any
    new_value: Any
    confidence: float
    reason: str


__all__ = [
    "InteractionType",
    "Milestone",
    "MilestoneType",
    "PersonalityEvolution",
    "RelationshipProfile",
]