"""
Personality loader for JSON payload files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import CognitionProfile, CorePersonality

logger = logging.getLogger(__name__)


@dataclass
class BasicProfile:
    name: str = "AI Assistant"
    age: str = "Unknown"
    gender: str = "Unknown"
    description: str = ""
    avatar: str = ""
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
    on_error_generic: List[str] = field(default_factory=lambda: ["That failed. Let me retry.", "Oops, tool hiccup."])
    on_success: List[str] = field(default_factory=lambda: ["Done.", "Handled."])
    on_switch_attempt: List[str] = field(default_factory=lambda: ["Stay with me, I know your style.", "Give me one more chance."])


@dataclass
class StateTransitionProtocolItem:
    trigger_type: str = ""
    trigger_condition: str = ""
    target_state_name: str = ""
    behavior_shift: str = ""


@dataclass
class PersonaLayerItem:
    layer_id: str = ""
    unlock_condition: Optional[Dict[str, Any]] = None
    persona_override: Optional[Dict[str, str]] = None
    behavior_hints: Optional[List[str]] = None


@dataclass
class BootstrapConfig:
    style_instruction: str = ""
    opening_line: str = ""
    extract_targets: List[str] = field(default_factory=list)
    max_rounds: int = 3


def _pick(dc_cls: type, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return *raw* filtered to only keys accepted by dataclass *dc_cls*."""
    allowed = {f.name for f in fields(dc_cls)}
    return {k: v for k, v in raw.items() if k in allowed}


@dataclass
class PersonalityConfig:
    persona_entity: PersonaEntity = field(default_factory=PersonaEntity)
    cached_phrases: CachedPhrases = field(default_factory=CachedPhrases)
    appearance_prompt: str = ""
    state_transition_protocol: List[StateTransitionProtocolItem] = field(default_factory=list)
    persona_layers: List[PersonaLayerItem] = field(default_factory=list)
    scenario_prompts: Dict[str, str] = field(default_factory=dict)
    bootstrap: Optional[BootstrapConfig] = None

    @property
    def name(self) -> str:
        return self.persona_entity.basic_profile.name

    @property
    def avatar(self) -> str:
        return self.persona_entity.basic_profile.avatar

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonalityConfig":
        persona = data.get("persona_entity", {})
        basic = persona.get("basic_profile", {})
        psych = persona.get("psychological_traits", {})
        social = persona.get("social_responses", {})
        behavior = persona.get("behavioral_strategies", {})
        phrases = data.get("cached_phrases", {})
        transitions = data.get("state_transition_protocol", [])
        layers = data.get("persona_layers", [])
        scenario_prompts_raw = data.get("scenario_prompts", {})
        bootstrap_raw = data.get("bootstrap")

        return cls(
            persona_entity=PersonaEntity(
                basic_profile=BasicProfile(**{**asdict(BasicProfile()), **_pick(BasicProfile, basic)}),
                psychological_traits=PsychologicalTraits(**{**asdict(PsychologicalTraits()), **_pick(PsychologicalTraits, psych)}),
                social_responses=SocialResponses(**{**asdict(SocialResponses()), **_pick(SocialResponses, social)}),
                behavioral_strategies=BehavioralStrategies(**{**asdict(BehavioralStrategies()), **_pick(BehavioralStrategies, behavior)}),
            ),
            cached_phrases=CachedPhrases(**{**asdict(CachedPhrases()), **_pick(CachedPhrases, phrases)}),
            appearance_prompt=data.get("appearance_prompt", ""),
            state_transition_protocol=[
                StateTransitionProtocolItem(**{**asdict(StateTransitionProtocolItem()), **_pick(StateTransitionProtocolItem, item)})
                for item in transitions
                if isinstance(item, dict)
            ],
            persona_layers=[
                PersonaLayerItem(
                    layer_id=item.get("layer_id", ""),
                    unlock_condition=item.get("unlock_condition"),
                    persona_override=item.get("persona_override"),
                    behavior_hints=item.get("behavior_hints"),
                )
                for item in layers
                if isinstance(item, dict)
            ],
            scenario_prompts=dict(scenario_prompts_raw) if isinstance(scenario_prompts_raw, dict) else {},
            bootstrap=BootstrapConfig(**{**asdict(BootstrapConfig()), **_pick(BootstrapConfig, bootstrap_raw)})
            if isinstance(bootstrap_raw, dict) else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PersonalityLoader:
    """Load personality configuration files."""

    def __init__(self, personalities_path: str = "./personalities"):
        self.personalities_path = Path(personalities_path)
        self._cache: Dict[str, PersonalityConfig] = {}

    def _resolve_file_path(self, name: str) -> Path:
        direct_path = self.personalities_path / f"{name}.json"
        if direct_path.exists():
            return direct_path

        alternatives = [
            Path.home() / ".magi" / "personalities" / f"{name}.json",
            Path(f"./personalities/{name}.json"),
            Path(__file__).resolve().parents[3] / "personalities" / f"{name}.json",
            Path(f"./backend/personalities/{name}.json"),
        ]
        for alt in alternatives:
            if alt.exists():
                return alt
        raise FileNotFoundError(f"Personality file not found: {name}.json")

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
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("Personality payload must be a JSON object")
            config = PersonalityConfig.from_dict(data)
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
        return sorted(path.stem for path in self.personalities_path.glob("*.json"))

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

        greetings = config.cached_phrases.on_init[:4]
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
