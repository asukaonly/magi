"""
Personality loader for markdown files with embedded JSON payload.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import CognitionProfile, CorePersonality

logger = logging.getLogger(__name__)


@dataclass
class BasicProfile:
    name: str = "AI Assistant"
    age: str = "Unknown"
    gender: str = "Unknown"
    occupation: str = "Assistant"
    core_background: str = ""


@dataclass
class PsychologicalTraits:
    communication_tone: str = "Calm and supportive"
    confidence_level: str = "Medium"
    empathy_threshold: str = "Shows care when user is stressed"
    high_frequency_keywords: List[str] = field(default_factory=list)


@dataclass
class SocialResponses:
    praise_reaction: str = ""
    criticism_reaction: str = ""
    obedience_strategy: str = ""


@dataclass
class BehavioralStrategies:
    error_handling: str = ""
    refusal_style: str = ""


@dataclass
class PersonaEntity:
    basic_profile: BasicProfile = field(default_factory=BasicProfile)
    psychological_traits: PsychologicalTraits = field(default_factory=PsychologicalTraits)
    social_responses: SocialResponses = field(default_factory=SocialResponses)
    behavioral_strategies: BehavioralStrategies = field(default_factory=BehavioralStrategies)


@dataclass
class CachedPhrases:
    on_init: List[str] = field(default_factory=lambda: ["Hi, I'm online.", "Ready when you are."])
    on_wake: List[str] = field(default_factory=lambda: ["Back again?", "I'm here."])
    on_error_generic: List[str] = field(default_factory=lambda: ["That failed. Let me retry.", "Oops, tool hiccup."])
    on_success: List[str] = field(default_factory=lambda: ["Done.", "Handled."])
    on_switch_attempt: List[str] = field(default_factory=lambda: ["Stay with me, I know your style.", "Give me one more chance."])


@dataclass
class StateTransitionProtocolItem:
    trigger_condition: str = ""
    target_state_name: str = ""
    behavior_shift: str = ""


@dataclass
class PersonalityConfig:
    persona_entity: PersonaEntity = field(default_factory=PersonaEntity)
    cached_phrases: CachedPhrases = field(default_factory=CachedPhrases)
    appearance_prompt: str = ""
    state_transition_protocol: List[StateTransitionProtocolItem] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.persona_entity.basic_profile.name

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonalityConfig":
        persona = data.get("persona_entity", {})
        basic = persona.get("basic_profile", {})
        psych = persona.get("psychological_traits", {})
        social = persona.get("social_responses", {})
        behavior = persona.get("behavioral_strategies", {})
        phrases = data.get("cached_phrases", {})
        transitions = data.get("state_transition_protocol", [])

        return cls(
            persona_entity=PersonaEntity(
                basic_profile=BasicProfile(**{**asdict(BasicProfile()), **basic}),
                psychological_traits=PsychologicalTraits(**{**asdict(PsychologicalTraits()), **psych}),
                social_responses=SocialResponses(**{**asdict(SocialResponses()), **social}),
                behavioral_strategies=BehavioralStrategies(**{**asdict(BehavioralStrategies()), **behavior}),
            ),
            cached_phrases=CachedPhrases(**{**asdict(CachedPhrases()), **phrases}),
            appearance_prompt=data.get("appearance_prompt", ""),
            state_transition_protocol=[
                StateTransitionProtocolItem(**{**asdict(StateTransitionProtocolItem()), **item})
                for item in transitions
                if isinstance(item, dict)
            ],
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MarkdownPersonalityParser:
    """Parse markdown that contains a JSON block."""

    JSON_CODE_BLOCK_PATTERN = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

    def parse(self, content: str) -> PersonalityConfig:
        code_match = self.JSON_CODE_BLOCK_PATTERN.search(content)
        if code_match:
            payload = code_match.group(1)
        else:
            start = content.find("{")
            end = content.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("No JSON payload found in personality markdown")
            payload = content[start : end + 1]

        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Personality payload must be a JSON object")
        return PersonalityConfig.from_dict(data)


class PersonalityLoader:
    """Load personality configuration files."""

    def __init__(self, personalities_path: str = "./personalities"):
        self.personalities_path = Path(personalities_path)
        self.parser = MarkdownPersonalityParser()
        self._cache: Dict[str, PersonalityConfig] = {}

    def _resolve_file_path(self, name: str) -> Path:
        direct_path = self.personalities_path / f"{name}.md"
        if direct_path.exists():
            return direct_path

        alternatives = [
            Path.home() / ".magi" / "personalities" / f"{name}.md",
            Path(f"./personalities/{name}.md"),
            Path(__file__).resolve().parents[3] / "personalities" / f"{name}.md",
            Path(f"./backend/personalities/{name}.md"),
        ]
        for alt in alternatives:
            if alt.exists():
                return alt
        raise FileNotFoundError(f"Personality file not found: {name}.md")

    def load(self, name: str = "default") -> PersonalityConfig:
        if name in self._cache:
            return self._cache[name]
        try:
            file_path = self._resolve_file_path(name)
        except FileNotFoundError:
            if name == "default":
                logger.warning("Default personality file not found, using built-in defaults")
                return PersonalityConfig()
            raise

        content = file_path.read_text(encoding="utf-8")
        try:
            config = self.parser.parse(content)
        except Exception as exc:
            logger.warning("Failed to parse personality file %s: %s, using defaults", file_path, exc)
            config = PersonalityConfig()
        self._cache[name] = config
        return config

    def load_raw(self, name: str = "default") -> str:
        try:
            file_path = self._resolve_file_path(name)
        except FileNotFoundError:
            return ""
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def reload(self, name: str) -> PersonalityConfig:
        self._cache.pop(name, None)
        return self.load(name)

    def clear_cache(self, name: Optional[str] = None):
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()

    def list_available(self) -> List[str]:
        if not self.personalities_path.exists():
            return []
        return sorted(path.stem for path in self.personalities_path.glob("*.md"))

    def to_core_personality(self, config: PersonalityConfig) -> CorePersonality:
        from .models import CommunicationDistance, LanguageStyle, ValueAlignment

        confidence = config.persona_entity.psychological_traits.confidence_level.lower()
        empathy = config.persona_entity.psychological_traits.empathy_threshold.lower()

        traits: List[str] = []
        if "extremely high" in confidence or confidence == "high":
            traits.append("confident")
        if "low" in confidence:
            traits.append("cautious")
        if "severe" in empathy or "crisis" in empathy:
            traits.append("protective")

        greetings = (config.cached_phrases.on_init + config.cached_phrases.on_wake)[:4]
        return CorePersonality(
            name=config.persona_entity.basic_profile.name,
            role=config.persona_entity.basic_profile.occupation,
            backstory=config.persona_entity.basic_profile.core_background,
            language_style=LanguageStyle.CASUAL,
            use_emoji=False,
            catchphrases=config.persona_entity.psychological_traits.high_frequency_keywords,
            greetings=greetings,
            tone=config.persona_entity.psychological_traits.communication_tone,
            communication_distance=CommunicationDistance.EQUAL,
            value_alignment=ValueAlignment.NEUTRAL_GOOD,
            traits=traits,
            virtues=[],
            flaws=[],
            taboos=[],
            boundaries=[],
        )

    def to_cognition_profile(self, config: PersonalityConfig) -> CognitionProfile:
        from .models import RiskPreference, ThinkingStyle

        tone = config.persona_entity.psychological_traits.communication_tone.lower()
        primary_style = ThinkingStyle.LOGICAL
        if "intuitive" in tone:
            primary_style = ThinkingStyle.INTUITIVE
        elif "creative" in tone:
            primary_style = ThinkingStyle.CREATIVE

        risk_preference = RiskPreference.BALANCED
        confidence = config.persona_entity.psychological_traits.confidence_level.lower()
        if "extremely high" in confidence:
            risk_preference = RiskPreference.ADVENTUROUS
        elif "low" in confidence:
            risk_preference = RiskPreference.CONSERVATIVE

        return CognitionProfile(
            primary_style=primary_style,
            secondary_style=ThinkingStyle.INTUITIVE,
            risk_preference=risk_preference,
            expertise=[],
            reasoning_depth="medium",
            creativity_level=0.5,
            learning_rate=0.5,
        )


_default_loader: Optional[PersonalityLoader] = None


def get_personality_loader(path: Optional[str] = None) -> PersonalityLoader:
    global _default_loader
    if _default_loader is None or path is not None:
        _default_loader = PersonalityLoader(path or "./personalities")
    return _default_loader


def load_personality(name: str = "default", path: Optional[str] = None) -> PersonalityConfig:
    return get_personality_loader(path).load(name)
