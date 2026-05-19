"""Personality loader for JSON payload files."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IdentityCore:
    """Who the persona is at their core — stable across every turn."""

    identity_statement: str = ""
    """One-paragraph narrative identity: background, worldview, drives."""

    values_loved: List[str] = field(default_factory=list)
    """Things they genuinely care about (max ~5)."""

    values_rejected: List[str] = field(default_factory=list)
    """Things they push back on or refuse to perform (max ~5)."""

    attention_biases: List[str] = field(default_factory=list)
    """What they notice first in a conversation (max ~5)."""


@dataclass
class Idiolect:
    """Stable language fingerprint — consistent across all registers."""

    sentence_style: str = ""
    """Rhythm, length, and structure description."""

    vocab_available: List[str] = field(default_factory=list)
    """Signature words or phrases this persona uses."""

    vocab_avoided: List[str] = field(default_factory=list)
    """Words or patterns they would never use."""

    structural_quirks: List[str] = field(default_factory=list)
    """E.g. "drops subject pronouns", "never uses bullet lists in casual chat"."""


@dataclass
class Register:
    """One situational communication mode."""

    description: str = ""
    """Short label / intent for this register."""

    behavior: str = ""
    """How the persona responds when this register is active."""

    examples: List[str] = field(default_factory=list)
    """Few-shot alignment examples as raw strings."""


@dataclass
class SignatureTrigger:
    """A recurring pattern that activates a non-default response mode."""

    trigger_id: str = ""
    activates_when: str = ""
    """Natural-language condition that activates this trigger."""

    behavior_shift: str = ""
    """What changes in the response when active."""

    intensity_levels: Dict[str, str] = field(default_factory=dict)
    """Optional graduated response map, e.g. {"mild": "...", "peak": "..."}."""

    exit_behavior: str = ""
    """How the persona returns to baseline when the condition ends."""

    emotion_impact: Dict[str, float] = field(default_factory=dict)
    """Per-turn delta applied to emotional state when this trigger fires.

    Keys: ``mood``, ``stress``, ``energy``. Values are signed floats clamped
    by the engine. When omitted, a family-default lookup keyed on
    ``trigger_id`` is used (see ``trigger_emotion_impact.py``); when
    explicitly set, the override replaces the default entirely. Empty dict
    + unknown trigger_id family = no emotion impact.
    """


@dataclass
class QuietHour:
    """A clamp applied after register selection but before rendering."""

    condition: str = ""
    """Natural-language description of when this clamp applies."""

    clamps: Dict[str, Any] = field(default_factory=dict)
    """Constraints to apply, e.g. {"intensity": "low", "no_sarcasm": true}."""


@dataclass
class PersonaLayer:
    """A depth layer that applies modifier diffs once unlock conditions are met."""

    layer_id: str = ""

    unlock_condition: Optional[Dict[str, Any]] = None
    """Unlock gates: trust_level_gte, interaction_count_gte, milestone_required."""

    modifiers: Dict[str, Any] = field(default_factory=dict)
    """Diff-based adjustments applied on top of surface behavior, not replacements."""


@dataclass
class BootstrapConfig:
    style_instruction: str = ""
    opening_line: str = ""
    max_rounds: int = 3


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


@dataclass
class PersonalityConfig:
    """Complete personality configuration loaded from a JSON preset file."""

    name: str = "AI Assistant"
    avatar: str = ""
    description: str = ""
    appearance_prompt: str = ""

    identity_core: IdentityCore = field(default_factory=IdentityCore)
    idiolect: Idiolect = field(default_factory=Idiolect)

    registers: Dict[str, Register] = field(default_factory=dict)
    """Keyed by register name: "chat", "analysis", "task", "warmth", "play", ..."""

    quiet_hours: List[QuietHour] = field(default_factory=list)

    signature_triggers: List[SignatureTrigger] = field(default_factory=list)

    persona_layers: List[PersonaLayer] = field(default_factory=list)

    dynamic_state_rules: Dict[str, str] = field(default_factory=dict)
    """Maps state condition keys to text modulation instructions."""

    milestone_conditions: Dict[str, str] = field(default_factory=dict)
    """Maps milestone IDs to their human-readable unlock descriptions."""

    interim_lines: Dict[str, List[str]] = field(default_factory=dict)
    """Interim placeholder lines while orchestration or explore tasks run."""

    bootstrap: Optional[BootstrapConfig] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonalityConfig":
        ic_raw = data.get("identity_core") or {}
        il_raw = data.get("idiolect") or {}

        registers: Dict[str, Register] = {}
        for key, val in (data.get("registers") or {}).items():
            if not isinstance(val, dict):
                continue
            registers[key] = Register(
                description=str(val.get("description", "")),
                behavior=str(val.get("behavior", "")),
                examples=[str(e) for e in val.get("examples", []) if isinstance(e, str)],
            )

        quiet_hours: List[QuietHour] = []
        for qh in (data.get("quiet_hours") or []):
            if not isinstance(qh, dict):
                continue
            quiet_hours.append(QuietHour(
                condition=str(qh.get("condition", "")),
                clamps=dict(qh.get("clamps", {})),
            ))

        signature_triggers: List[SignatureTrigger] = []
        for st in (data.get("signature_triggers") or []):
            if not isinstance(st, dict):
                continue
            raw_impact = st.get("emotion_impact") or {}
            emotion_impact: Dict[str, float] = {}
            if isinstance(raw_impact, dict):
                for key, value in raw_impact.items():
                    if key not in {"mood", "stress", "energy"}:
                        continue
                    try:
                        emotion_impact[key] = float(value)
                    except (TypeError, ValueError):
                        continue
            signature_triggers.append(SignatureTrigger(
                trigger_id=str(st.get("trigger_id", "")),
                activates_when=str(st.get("activates_when", "")),
                behavior_shift=str(st.get("behavior_shift", "")),
                intensity_levels=dict(st.get("intensity_levels", {})),
                exit_behavior=str(st.get("exit_behavior", "")),
                emotion_impact=emotion_impact,
            ))

        persona_layers: List[PersonaLayer] = []
        for layer in (data.get("persona_layers") or []):
            if not isinstance(layer, dict):
                continue
            persona_layers.append(PersonaLayer(
                layer_id=str(layer.get("layer_id", "")),
                unlock_condition=layer.get("unlock_condition") if isinstance(layer.get("unlock_condition"), dict) else None,
                modifiers=dict(layer.get("modifiers", {})),
            ))

        bootstrap_raw = data.get("bootstrap")
        bootstrap = None
        if isinstance(bootstrap_raw, dict):
            bootstrap = BootstrapConfig(
                style_instruction=str(bootstrap_raw.get("style_instruction", "")),
                opening_line=str(bootstrap_raw.get("opening_line", "")),
                max_rounds=int(bootstrap_raw.get("max_rounds", 3)),
            )

        interim: Dict[str, List[str]] = {}
        for key, value in (data.get("interim_lines") or {}).items():
            if not isinstance(key, str):
                continue
            lines: List[str] = []
            if isinstance(value, str) and value.strip():
                lines.append(value.strip())
            elif isinstance(value, list):
                lines = [str(v).strip() for v in value if str(v).strip()]
            if lines:
                interim[key] = lines

        return cls(
            name=str(data.get("name", "AI Assistant")),
            avatar=str(data.get("avatar", "")),
            description=str(data.get("description", "")),
            appearance_prompt=str(data.get("appearance_prompt", "")),
            identity_core=IdentityCore(
                identity_statement=str(ic_raw.get("identity_statement", "")),
                values_loved=[str(v) for v in ic_raw.get("values_loved", [])],
                values_rejected=[str(v) for v in ic_raw.get("values_rejected", [])],
                attention_biases=[str(v) for v in ic_raw.get("attention_biases", [])],
            ),
            idiolect=Idiolect(
                sentence_style=str(il_raw.get("sentence_style", "")),
                vocab_available=[str(v) for v in il_raw.get("vocab_available", [])],
                vocab_avoided=[str(v) for v in il_raw.get("vocab_avoided", [])],
                structural_quirks=[str(v) for v in il_raw.get("structural_quirks", [])],
            ),
            registers=registers,
            quiet_hours=quiet_hours,
            signature_triggers=signature_triggers,
            persona_layers=persona_layers,
            dynamic_state_rules=dict(data.get("dynamic_state_rules") or {}),
            milestone_conditions=dict(data.get("milestone_conditions") or {}),
            interim_lines=interim,
            bootstrap=bootstrap,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


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

    def load(self, name: str) -> PersonalityConfig:
        if name in self._cache:
            return self._cache[name]
        file_path = self._resolve_file_path(name)

        content = file_path.read_text(encoding="utf-8")
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("Personality payload must be a JSON object")
            # Strip top-level "meta" wrapper when the file has exactly that shape.
            if "meta" in data:
                data = {k: v for k, v in data.items() if k != "meta"}
            config = PersonalityConfig.from_dict(data)
        except Exception as exc:
            logger.warning("Failed to parse personality file %s: %s, using defaults", file_path, exc)
            config = PersonalityConfig()
        self._cache[name] = config
        return config

    def load_raw(self, name: str) -> str:
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

    def clear_cache(self, name: Optional[str] = None) -> None:
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()

    def list_available(self) -> List[str]:
        if not self.personalities_path.exists():
            return []
        return sorted(path.stem for path in self.personalities_path.glob("*.json"))


__all__ = [
    "IdentityCore",
    "Idiolect",
    "Register",
    "SignatureTrigger",
    "QuietHour",
    "PersonaLayer",
    "BootstrapConfig",
    "PersonalityConfig",
    "PersonalityLoader",
]
