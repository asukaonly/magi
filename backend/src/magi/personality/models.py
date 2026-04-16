"""
Memory Systemdata Models

Internal note.
"""
import time
from typing import Dict, List
from enum import Enum
from dataclasses import dataclass, field


# Internal note.

class LanguageStyle(Enum):
    """Language style"""
    CONCISE = "concise"
    VERBOSE = "verbose"
    FORMAL = "formal"
    CASUAL = "casual"
    TECHNICAL = "technical"
    POETIC = "poetic"


class CommunicationDistance(Enum):
    """Communication distance"""
    INTIMATE = "intimate"
    EQUAL = "equal"
    RESPECTFUL = "respectful"
    SUBSERVIENT = "subservient"
    DETACHED = "detached"


class ValueAlignment(Enum):
    """Value alignment"""
    LAWFUL_GOOD = "lawful_good"
    NEUTRAL_GOOD = "neutral_good"
    CHAOTIC_GOOD = "chaotic_good"
    LAWFUL_NEUTRAL = "lawful_neutral"
    TRUE_NEUTRAL = "true_neutral"
    CHAOTIC_NEUTRAL = "chaotic_neutral"
    LAWFUL_EVIL = "lawful_evil"
    NEUTRAL_EVIL = "neutral_evil"
    CHAOTIC_EVIL = "chaotic_evil"


class RiskPreference(Enum):
    """Risk preference"""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    ADVENTUROUS = "adventurous"


class ThinkingStyle(Enum):
    """Thinking style"""
    LOGICAL = "logical"
    CREATIVE = "creative"
    INTUITIVE = "intuitive"
    ANALYTICAL = "analytical"


class AmbiguityTolerance(Enum):
    """Ambiguity tolerance"""
    IMPATIENT = "impatient"
    CAUTIOUS = "cautious"
    ADAPTIVE = "adaptive"


# ===== data Models =====

@dataclass
class CorePersonality:
    """Core personality layer"""
    name: str
    role: str
    backstory: str = ""
    language_style: LanguageStyle = LanguageStyle.CASUAL
    use_emoji: bool = False
    catchphrases: List[str] = field(default_factory=list)
    greetings: List[str] = field(default_factory=list)
    tone: str = "friendly"
    communication_distance: CommunicationDistance = CommunicationDistance.EQUAL
    value_alignment: ValueAlignment = ValueAlignment.NEUTRAL_GOOD
    traits: List[str] = field(default_factory=list)
    virtues: List[str] = field(default_factory=list)
    flaws: List[str] = field(default_factory=list)
    taboos: List[str] = field(default_factory=list)
    boundaries: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class DomainExpertise:
    """Domain expertise"""
    domain: str
    level: float
    confidence: float = 0.5


@dataclass
class CognitionProfile:
    """Cognitive capability layer"""
    primary_style: ThinkingStyle = ThinkingStyle.LOGICAL
    secondary_style: ThinkingStyle = ThinkingStyle.INTUITIVE
    risk_preference: RiskPreference = RiskPreference.BALANCED
    expertise: List[DomainExpertise] = field(default_factory=list)
    reasoning_depth: str = "medium"
    creativity_level: float = 0.5
    skepticism_level: float = 0.3
    learning_rate: float = 0.5
    adaptation_speed: str = "medium"


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
    updated_at: float = field(default_factory=time.time)


@dataclass
class GrowthMemory:
    """Growth memory layer"""
    milestones: List[Dict] = field(default_factory=list)
    total_interactions: int = 0
    interaction_days: int = 0
    learned_capabilities: List[str] = field(default_factory=list)
    personality_evolution: List[Dict] = field(default_factory=list)
    relationship_depth: Dict[str, float] = field(default_factory=dict)
