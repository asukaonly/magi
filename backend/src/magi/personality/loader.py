"""
Personality loader for JSON payload files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BasicProfile:
    name: str = "AI Assistant"
    age: str = "Unknown"
    gender: str = "Unknown"
    description: str = ""
    avatar: str = ""
    occupation: str = "Assistant"


@dataclass
class CoreIdentity:
    inner_narrative: str = ""
    language_fingerprint: str = ""
    attention_bias: str = ""


@dataclass
class PersonaEntity:
    basic_profile: BasicProfile = field(default_factory=BasicProfile)
    core_identity: CoreIdentity = field(default_factory=CoreIdentity)


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


def _synthesize_core_identity(persona: Dict[str, Any]) -> Dict[str, str]:
    """Build core_identity from legacy psychological_traits / social_responses / behavioral_strategies."""
    psych = persona.get("psychological_traits", {})
    social = persona.get("social_responses", {})
    behavior = persona.get("behavioral_strategies", {})
    bg = persona.get("basic_profile", {}).get("core_background", "")

    parts_narrative: List[str] = []
    if bg:
        parts_narrative.append(bg)
    tone = psych.get("communication_tone", "")
    if tone:
        parts_narrative.append(tone)
    empathy = psych.get("empathy_threshold", "")
    if empathy:
        parts_narrative.append(empathy)

    parts_fingerprint: List[str] = []
    keywords = psych.get("high_frequency_keywords", [])
    if keywords:
        parts_fingerprint.append(f"High-frequency keywords: {', '.join(keywords)}")
    praise = social.get("praise_reaction", "")
    if praise:
        parts_fingerprint.append(f"Praise reaction: {praise}")
    criticism = social.get("criticism_reaction", "")
    if criticism:
        parts_fingerprint.append(f"Criticism reaction: {criticism}")
    error = behavior.get("error_handling", "")
    if error:
        parts_fingerprint.append(f"Error handling: {error}")
    refusal = behavior.get("refusal_style", "")
    if refusal:
        parts_fingerprint.append(f"Refusal style: {refusal}")

    return {
        "inner_narrative": " ".join(parts_narrative),
        "language_fingerprint": " | ".join(parts_fingerprint),
        "attention_bias": "",
    }


@dataclass
class PersonalityConfig:
    persona_entity: PersonaEntity = field(default_factory=PersonaEntity)
    appearance_prompt: str = ""
    state_transition_protocol: List[StateTransitionProtocolItem] = field(default_factory=list)
    persona_layers: List[PersonaLayerItem] = field(default_factory=list)
    milestone_conditions: Dict[str, str] = field(default_factory=dict)
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
        identity_raw = persona.get("core_identity", {})
        transitions = data.get("state_transition_protocol", [])
        layers = data.get("persona_layers", [])
        scenario_prompts_raw = data.get("scenario_prompts", {})
        bootstrap_raw = data.get("bootstrap")

        # Backward-compat: synthesize core_identity from legacy fields
        if not identity_raw and persona:
            identity_raw = _synthesize_core_identity(persona)

        return cls(
            persona_entity=PersonaEntity(
                basic_profile=BasicProfile(**{**asdict(BasicProfile()), **_pick(BasicProfile, basic)}),
                core_identity=CoreIdentity(**{**asdict(CoreIdentity()), **_pick(CoreIdentity, identity_raw)}),
            ),
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
            milestone_conditions=dict(data.get("milestone_conditions", {})),
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


_default_loader: Optional[PersonalityLoader] = None


def get_personality_loader(path: Optional[str] = None) -> PersonalityLoader:
    global _default_loader
    if _default_loader is None or path is not None:
        _default_loader = PersonalityLoader(path or "./personalities")
    return _default_loader


def load_personality(name: str = "default", path: Optional[str] = None) -> PersonalityConfig:
    return get_personality_loader(path).load(name)
