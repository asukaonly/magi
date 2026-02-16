"""
Memory Systemdata Models

定义all层级的datastructure，避免循环import
"""
import time
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass, field


# ===== 枚举定义 =====

class LanguageStyle(Enum):
    """语言style"""
    CONCISE = "concise"
    VERBOSE = "verbose"
    FORMAL = "formal"
    CasUAL = "casual"
    TECHNICAL = "technical"
    POETIC = "poetic"


class CommunicationDistance(Enum):
    """沟通distance感"""
    intIMATE = "intimate"
    EQUAL = "equal"
    RESPECTFUL = "respectful"
    subSERVIENT = "subservient"
    detachED = "detached"


class ValueAlignment(Enum):
    """base价Value观 - D&D阵营"""
    LAWFUL_GOOD = "lawful_good"
    NEUTRAL_GOOD = "neutral_good"
    CHAOTIC_GOOD = "chaotic_good"
    LAWFUL_NEUTRAL = "lawful_neutral"
    true_NEUTRAL = "true_neutral"
    CHAOTIC_NEUTRAL = "chaotic_neutral"
    LAWFUL_EVIL = "lawful_evil"
    NEUTRAL_EVIL = "neutral_evil"
    CHAOTIC_EVIL = "chaotic_evil"


class RiskPreference(Enum):
    """风险preference"""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    ADVENTUROUS = "adventurous"


class ThinkingStyle(Enum):
    """思维style"""
    LOGICAL = "logical"
    CREATIVE = "creative"
    intUITIVE = "intuitive"
    ANALYTICAL = "analytical"


class AmbiguityTolerance(Enum):
    """模糊容忍度"""
    IMPATIENT = "impatient"
    CAUTIOUS = "cautious"
    ADAPTIVE = "adaptive"


# ===== data Models =====

@dataclass
class CorePersonality:
    """corepersonality层 - AI的基本Property"""
    name: str
    role: str
    backstory: str = ""
    language_style: LanguageStyle = LanguageStyle.CasUAL
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
    """领域专精"""
    domain: str
    level: float
    confidence: float = 0.5


@dataclass
class CognitionProfile:
    """认知capability层"""
    primary_style: ThinkingStyle = ThinkingStyle.LOGICAL
    secondary_style: ThinkingStyle = ThinkingStyle.intUITIVE
    risk_preference: RiskPreference = RiskPreference.BALANCED
    expertise: List[DomainExpertise] = field(default_factory=list)
    reasoning_depth: str = "medium"
    creativity_level: float = 0.5
    skepticism_level: float = 0.3
    learning_rate: float = 0.5
    adaptation_speed: str = "medium"


@dataclass
class TaskBehaviorProfile:
    """row为preference层"""
    task_category: str
    information_density: str = "medium"
    ambiguity_tolerance: AmbiguityTolerance = AmbiguityTolerance.ADAPTIVE
    response_prefers: List[str] = field(default_factory=list)
    response_avoids: List[str] = field(default_factory=list)
    error_tolerance: float = 0.5
    proactivity: str = "reactive"


@dataclass
class EmotionalState:
    """emotionState层"""
    current_mood: str = "neutral"
    mood_intensity: float = 0.5
    energy_level: float = 0.7
    stress_level: float = 0.2
    focus_state: str = "notttrmal"
    social_state: str = "neutral"
    updated_at: float = field(default_factory=time.time)


@dataclass
class GrowthMemory:
    """growthmemory层"""
    milestones: List[Dict] = field(default_factory=list)
    total_interactions: int = 0
    interaction_days: int = 0
    learned_capabilities: List[str] = field(default_factory=list)
    personality_evolution: List[Dict] = field(default_factory=list)
    relationship_depth: Dict[str, float] = field(default_factory=dict)
