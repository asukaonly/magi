"""Per-turn persona behavior planning."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from .loader import PersonalityConfig, Register


_CRISIS_TERMS = (
    "crisis",
    "urgent",
    "emergency",
    "leak",
    "hacked",
    "stolen",
    "password",
    "紧急",
    "泄露",
    "被盗",
    "入侵",
    "密码",
)
_EMOTIONAL_TERMS = (
    "sad",
    "tired",
    "anxious",
    "overwhelmed",
    "upset",
    "难受",
    "崩溃",
    "焦虑",
    "累",
    "心情",
    "撑不住",
)
_DOMAIN_TERMS = (
    "architecture",
    "code",
    "system",
    "prompt",
    "model",
    "runtime",
    "schema",
    "架构",
    "代码",
    "系统",
    "模型",
    "链路",
    "配置",
)
_PLAY_TERMS = (
    "absurd",
    "weird",
    "joke",
    "meme",
    "funny",
    "离谱",
    "抽象",
    "整活",
    "笑话",
    "乐子",
)
_VALUE_TERMS = (
    "evaluate",
    "opinion",
    "judge",
    "should",
    "worth",
    "评价",
    "怎么看",
    "该不该",
    "值不值",
)
_SERIOUS_TERMS = (
    "serious",
    "no joke",
    "stop joking",
    "认真",
    "别开玩笑",
    "严肃",
)


@dataclass(slots=True)
class ActivePersonaTrigger:
    """One signature trigger selected for the current turn."""

    trigger_id: str
    intensity: str
    behavior_shift: str
    reason: str = ""


@dataclass(slots=True)
class PersonaTurnPlan:
    """Persona behavior plan consumed by prompt rendering for one model call."""

    persona_name: str
    identity_core: dict[str, Any] = field(default_factory=dict)
    idiolect: dict[str, Any] = field(default_factory=dict)
    register: str = "casual"
    register_description: str = ""
    register_behavior: str = ""
    situation_strength: str = "ordinary"
    quiet_hours: list[dict[str, Any]] = field(default_factory=list)
    persona_intensity: int = 1
    active_triggers: list[ActivePersonaTrigger] = field(default_factory=list)
    active_layer: str | None = None
    layer_modifiers: dict[str, Any] = field(default_factory=dict)
    dynamic_modulations: dict[str, Any] = field(default_factory=dict)
    selected_examples: list[str] = field(default_factory=list)


class PersonaTurnPlanner:
    """Build a compact persona plan from config and runtime signals."""

    def build_plan(
        self,
        *,
        config: PersonalityConfig | None,
        user_message: str,
        scenario: str,
        task_category: str,
        tools: list[str] | None = None,
        relationship: dict[str, Any] | None = None,
        emotional_state: Any | None = None,
        milestones: list[dict[str, Any]] | None = None,
    ) -> PersonaTurnPlan:
        persona_config = config or PersonalityConfig()
        normalized_message = str(user_message or "")
        selected_tools = [str(tool) for tool in (tools or []) if str(tool).strip()]
        register_name = self._select_register(
            config=persona_config,
            user_message=normalized_message,
            scenario=scenario,
            task_category=task_category,
            tools=selected_tools,
        )
        register = persona_config.registers.get(register_name) or Register()
        active_layer, layer_modifiers = self._select_layer(
            config=persona_config,
            relationship=relationship or {},
            milestones=milestones or [],
        )
        dynamic_modulations = self._dynamic_modulations(
            config=persona_config,
            emotional_state=emotional_state,
        )
        active_triggers = self._select_triggers(
            config=persona_config,
            user_message=normalized_message,
            register=register_name,
            scenario=scenario,
            task_category=task_category,
        )
        quiet_hours = self._select_quiet_hours(
            config=persona_config,
            user_message=normalized_message,
            register=register_name,
            scenario=scenario,
            task_category=task_category,
            tools=selected_tools,
        )
        persona_intensity = self._persona_intensity(
            register=register_name,
            active_triggers=active_triggers,
            quiet_hours=quiet_hours,
        )
        situation_strength = "strong" if active_triggers else "ordinary"
        if register_name in {"task", "analysis", "crisis"}:
            situation_strength = register_name

        return PersonaTurnPlan(
            persona_name=persona_config.name,
            identity_core=asdict(persona_config.identity_core),
            idiolect=asdict(persona_config.idiolect),
            register=register_name,
            register_description=register.description,
            register_behavior=register.behavior,
            situation_strength=situation_strength,
            quiet_hours=quiet_hours,
            persona_intensity=persona_intensity,
            active_triggers=active_triggers,
            active_layer=active_layer,
            layer_modifiers=layer_modifiers,
            dynamic_modulations=dynamic_modulations,
            selected_examples=list(register.examples[:2]),
        )

    def _select_register(
        self,
        *,
        config: PersonalityConfig,
        user_message: str,
        scenario: str,
        task_category: str,
        tools: list[str],
    ) -> str:
        if self._contains_any(user_message, _CRISIS_TERMS):
            return self._first_available(config, ("crisis", "task", "analysis", "chat", "casual"))
        normalized_scenario = str(scenario or "").lower()
        normalized_task_category = str(task_category or "").lower()
        if normalized_scenario in {"analysis"} or "analysis" in normalized_task_category:
            return self._first_available(config, ("analysis", "task", "chat", "casual"))
        if (
            tools
            or normalized_scenario in {"task", "code", "debug"}
            or any(term in normalized_task_category for term in ("code", "debug", "execution", "task"))
        ):
            return self._first_available(config, ("task", "analysis", "chat", "casual"))
        if self._contains_any(user_message, _EMOTIONAL_TERMS):
            return self._first_available(config, ("emotional", "chat", "casual"))
        return self._first_available(config, ("casual", "chat", "task", "analysis"))

    def _select_triggers(
        self,
        *,
        config: PersonalityConfig,
        user_message: str,
        register: str,
        scenario: str,
        task_category: str,
    ) -> list[ActivePersonaTrigger]:
        selected: list[ActivePersonaTrigger] = []
        for trigger in config.signature_triggers:
            trigger_id = str(trigger.trigger_id or "").strip()
            if not trigger_id:
                continue
            reason = self._trigger_reason(
                trigger_id=trigger_id,
                activates_when=trigger.activates_when,
                user_message=user_message,
                register=register,
                scenario=scenario,
                task_category=task_category,
            )
            if not reason:
                continue
            selected.append(
                ActivePersonaTrigger(
                    trigger_id=trigger_id,
                    intensity=self._trigger_intensity(trigger.intensity_levels),
                    behavior_shift=trigger.behavior_shift,
                    reason=reason,
                )
            )
            if len(selected) >= 2:
                break
        return selected

    def _trigger_reason(
        self,
        *,
        trigger_id: str,
        activates_when: str,
        user_message: str,
        register: str,
        scenario: str,
        task_category: str,
    ) -> str:
        normalized_id = trigger_id.lower()
        if normalized_id == "crisis" and self._contains_any(user_message, _CRISIS_TERMS):
            return "crisis signal in user turn"
        if normalized_id in {"absurdity", "play"} and self._contains_any(user_message, _PLAY_TERMS):
            return "playful or absurdity signal in user turn"
        if normalized_id in {"domain_hotzone", "technical_interest"} and (
            register in {"analysis", "task"} or self._contains_any(user_message, _DOMAIN_TERMS)
        ):
            return "domain or technical analysis signal"
        if normalized_id in {"value_topic", "judgment"} and self._contains_any(user_message, _VALUE_TERMS):
            return "user asks for judgment or stance"
        if normalized_id in {"emotional_resonance", "emotional"} and self._contains_any(user_message, _EMOTIONAL_TERMS):
            return "user emotional state is salient"
        if self._condition_overlap(user_message, activates_when):
            return "persona trigger condition overlaps the user turn"
        _ = (scenario, task_category)
        return ""

    @staticmethod
    def _trigger_intensity(levels: dict[str, str]) -> str:
        for preferred in ("mid", "medium", "low", "mild", "high", "peak"):
            if preferred in levels:
                return preferred
        return "mid"

    def _select_quiet_hours(
        self,
        *,
        config: PersonalityConfig,
        user_message: str,
        register: str,
        scenario: str,
        task_category: str,
        tools: list[str],
    ) -> list[dict[str, Any]]:
        quiet_hours: list[dict[str, Any]] = []
        if register in {"task", "analysis"} or tools:
            quiet_hours.append({
                "condition": "focused_work",
                "clamps": {
                    "persona_intensity_max": 1,
                    "meme_density": "none",
                    "answer_utility": "highest",
                },
            })
        if register == "crisis":
            quiet_hours.append({
                "condition": "crisis",
                "clamps": {
                    "persona_intensity_max": 0,
                    "sarcasm": "none",
                    "answer_style": "brief_operational",
                },
            })
        if self._contains_any(user_message, _SERIOUS_TERMS):
            quiet_hours.append({
                "condition": "user_requested_seriousness",
                "clamps": {
                    "persona_intensity_max": 1,
                    "jokes": "none",
                },
            })

        for quiet_hour in config.quiet_hours:
            if self._condition_overlap(user_message, quiet_hour.condition):
                quiet_hours.append({
                    "condition": quiet_hour.condition,
                    "clamps": dict(quiet_hour.clamps),
                })
        _ = (scenario, task_category)
        return quiet_hours

    @staticmethod
    def _persona_intensity(
        *,
        register: str,
        active_triggers: list[ActivePersonaTrigger],
        quiet_hours: list[dict[str, Any]],
    ) -> int:
        if register == "crisis":
            return 0
        intensity = 2 if active_triggers else 1
        for quiet_hour in quiet_hours:
            clamps = quiet_hour.get("clamps") or {}
            max_intensity = clamps.get("persona_intensity_max")
            if isinstance(max_intensity, int):
                intensity = min(intensity, max_intensity)
        return max(0, min(3, intensity))

    @staticmethod
    def _select_layer(
        *,
        config: PersonalityConfig,
        relationship: dict[str, Any],
        milestones: list[dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any]]:
        active_layer: str | None = None
        modifiers: dict[str, Any] = {}
        milestone_keys = {
            str(item.get("key") or item.get("title") or item.get("id") or "").strip()
            for item in milestones
            if isinstance(item, dict)
        }
        for layer in config.persona_layers:
            condition = layer.unlock_condition or {}
            if not condition:
                active_layer = layer.layer_id or active_layer
                modifiers = dict(layer.modifiers)
                continue
            trust_required = condition.get("trust_level_gte")
            if trust_required is not None and float(relationship.get("trust_level", 0.0) or 0.0) < float(trust_required):
                continue
            interaction_required = condition.get("interaction_count_gte")
            if interaction_required is not None and int(relationship.get("interaction_count", 0) or 0) < int(interaction_required):
                continue
            milestone_required = str(condition.get("milestone_required") or "").strip()
            if milestone_required and milestone_required not in milestone_keys:
                continue
            active_layer = layer.layer_id or active_layer
            modifiers = dict(layer.modifiers)
        return active_layer, modifiers

    @staticmethod
    def _dynamic_modulations(
        *,
        config: PersonalityConfig,
        emotional_state: Any | None,
    ) -> dict[str, Any]:
        if emotional_state is None:
            return {}
        state = asdict(emotional_state) if is_dataclass(emotional_state) else dict(emotional_state or {})
        energy = float(state.get("energy_level", 0.7) or 0.7)
        stress = float(state.get("stress_level", 0.2) or 0.2)
        mood = str(state.get("current_mood") or state.get("mood") or "neutral").lower()
        active_rules: dict[str, str] = {}
        if energy < 0.35 and "low_energy" in config.dynamic_state_rules:
            active_rules["low_energy"] = config.dynamic_state_rules["low_energy"]
        if stress > 0.70 and "high_stress" in config.dynamic_state_rules:
            active_rules["high_stress"] = config.dynamic_state_rules["high_stress"]
        if mood in {"positive", "happy", "good", "excited"} and "positive_mood" in config.dynamic_state_rules:
            active_rules["positive_mood"] = config.dynamic_state_rules["positive_mood"]
        if not active_rules:
            return {}
        return {"active_rules": active_rules}

    @staticmethod
    def _first_available(config: PersonalityConfig, candidates: tuple[str, ...]) -> str:
        for candidate in candidates:
            if candidate in config.registers:
                return candidate
        if config.registers:
            return next(iter(config.registers.keys()))
        return candidates[0]

    @staticmethod
    def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
        normalized = text.lower()
        return any(term.lower() in normalized for term in terms)

    @staticmethod
    def _condition_overlap(user_message: str, condition: str) -> bool:
        message_terms = set(_tokenize_for_overlap(user_message))
        condition_terms = set(_tokenize_for_overlap(condition))
        if not message_terms or not condition_terms:
            return False
        return len(message_terms & condition_terms) >= 2


def _tokenize_for_overlap(text: str) -> list[str]:
    normalized = str(text or "").lower()
    latin_terms = re.findall(r"[a-z0-9_]{3,}", normalized)
    cjk_terms = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    return [*latin_terms, *cjk_terms]


__all__ = [
    "ActivePersonaTrigger",
    "PersonaTurnPlan",
    "PersonaTurnPlanner",
]
