"""
记忆系统数据模型

定义所有层级的数据结构，避免循环导入
"""
import time
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass, field


# ===== 枚举定义 =====

class LanguageStyle(Enum):
    """语言风格"""
    CONCISE = "concise"
    VERBOSE = "verbose"
    FORMAL = "formal"
    CASUAL = "casual"
    TECHNICAL = "technical"
    POETIC = "poetic"


class CommunicationDistance(Enum):
    """沟通距离感"""
    INTIMATE = "intimate"
    EQUAL = "equal"
    RESPECTFUL = "respectful"
    SUBSERVIENT = "subservient"
    DETACHED = "detached"


class ValueAlignment(Enum):
    """基础价值观 - D&D阵营"""
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
    """风险偏好"""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    ADVENTUROUS = "adventurous"


class ThinkingStyle(Enum):
    """思维风格"""
    LOGICAL = "logical"
    CREATIVE = "creative"
    INTUITIVE = "intuitive"
    ANALYTICAL = "analytical"


class AmbiguityTolerance(Enum):
    """模糊容忍度"""
    IMPATIENT = "impatient"
    CAUTIOUS = "cautious"
    ADAPTIVE = "adaptive"


# ===== 数据模型 =====

@dataclass
class CorePersonality:
    """核心人格层 - AI的基本属性"""
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
    """领域专精"""
    domain: str
    level: float
    confidence: float = 0.5


@dataclass
class CognitionProfile:
    """认知能力层"""
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
    """行为偏好层"""
    task_category: str
    information_density: str = "medium"
    ambiguity_tolerance: AmbiguityTolerance = AmbiguityTolerance.ADAPTIVE
    response_prefers: List[str] = field(default_factory=list)
    response_avoids: List[str] = field(default_factory=list)
    error_tolerance: float = 0.5
    proactivity: str = "reactive"


@dataclass
class EmotionalState:
    """情绪状态层"""
    current_mood: str = "neutral"
    mood_intensity: float = 0.5
    energy_level: float = 0.7
    stress_level: float = 0.2
    focus_state: str = "normal"
    social_state: str = "neutral"
    updated_at: float = field(default_factory=time.time)


@dataclass
class GrowthMemory:
    """成长记忆层"""
    milestones: List[Dict] = field(default_factory=list)
    total_interactions: int = 0
    interaction_days: int = 0
    learned_capabilities: List[str] = field(default_factory=list)
    personality_evolution: List[Dict] = field(default_factory=list)
    relationship_depth: Dict[str, float] = field(default_factory=dict)
