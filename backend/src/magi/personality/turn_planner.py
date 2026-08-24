"""Per-turn persona behavior planning."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from .loader import PersonalityConfig, Register, SignatureTrigger

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
    "疲惫",
    "心情",
    "撑不住",
    "硬撑",
    "撑着",
    "续命",
    "咖啡续命",
    "好困",
    "困死",
    "困了",
    "犯困",
    "熬夜",
    "没睡",
    "睡不够",
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
class PersonaRegisterCandidate:
    """One compact expression option exposed to the main model."""

    register: str
    description: str = ""
    behavior: str = ""
    reason: str = ""


@dataclass(slots=True)
class PersonaTurnPlan:
    """Persona policy, hard clamps, and candidates for one model call."""

    persona_name: str
    identity_core: dict[str, Any] = field(default_factory=dict)
    idiolect: dict[str, Any] = field(default_factory=dict)
    register: str = "casual"
    register_description: str = ""
    register_behavior: str = ""
    register_candidates: list[PersonaRegisterCandidate] = field(default_factory=list)
    register_is_hard_clamp: bool = False
    situation_strength: str = "ordinary"
    quiet_hours: list[dict[str, Any]] = field(default_factory=list)
    persona_intensity: int = 1
    active_triggers: list[ActivePersonaTrigger] = field(default_factory=list)
    active_layer: str | None = None
    layer_modifiers: dict[str, Any] = field(default_factory=dict)
    dynamic_modulations: dict[str, Any] = field(default_factory=dict)
    selected_examples: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class _TurnPlanningContext:
    config: PersonalityConfig
    user_message: str
    tools: list[str]
    relationship: dict[str, Any]
    milestones: list[dict[str, Any]]


@dataclass(slots=True, frozen=True)
class _TurnPlanState:
    register_name: str
    register: Register
    situation_strength: str
    quiet_hours: list[dict[str, Any]]
    persona_intensity: int
    active_triggers: list[ActivePersonaTrigger]
    active_layer: str | None
    layer_modifiers: dict[str, Any]
    dynamic_modulations: dict[str, Any]


def _normalized_tools(tools: list[str] | None) -> list[str]:
    return [str(tool) for tool in (tools or []) if str(tool).strip()]


def _turn_planning_context(
    *,
    config: PersonalityConfig | None,
    user_message: str,
    tools: list[str] | None,
    relationship: dict[str, Any] | None,
    milestones: list[dict[str, Any]] | None,
) -> _TurnPlanningContext:
    return _TurnPlanningContext(
        config=config or PersonalityConfig(),
        user_message=str(user_message or ""),
        tools=_normalized_tools(tools),
        relationship=relationship or {},
        milestones=milestones or [],
    )


def _signature_triggers_by_id(config: PersonalityConfig) -> dict[str, SignatureTrigger]:
    return {
        str(trigger.trigger_id or "").strip(): trigger
        for trigger in config.signature_triggers
        if str(trigger.trigger_id or "").strip()
    }


def _active_trigger(
    trigger_id: str,
    trigger: SignatureTrigger,
    *,
    reason: str,
) -> ActivePersonaTrigger:
    return ActivePersonaTrigger(
        trigger_id=trigger_id,
        intensity=_trigger_intensity(trigger.intensity_levels),
        behavior_shift=trigger.behavior_shift,
        reason=reason,
    )


def _trigger_intensity(levels: dict[str, str]) -> str:
    for preferred in ("mid", "medium", "low", "mild", "high", "peak"):
        if preferred in levels:
            return preferred
    return "mid"


def _built_in_quiet_hours(*, register: str, tools: list[str]) -> list[dict[str, Any]]:
    quiet_hours: list[dict[str, Any]] = []
    if register in {"task", "analysis"} or tools:
        quiet_hours.append(
            _quiet_hour_record(
                "focused_work",
                {
                    "persona_intensity_max": 1,
                    "meme_density": "none",
                    "answer_utility": "highest",
                },
            )
        )
    if register == "emotional":
        quiet_hours.append(
            _quiet_hour_record(
                "emotional_support",
                {
                    "persona_intensity_max": 1,
                    "sarcasm": "none_to_light",
                    "answer_utility": "highest",
                },
            )
        )
    if register == "crisis":
        quiet_hours.append(
            _quiet_hour_record(
                "crisis",
                {
                    "persona_intensity_max": 0,
                    "sarcasm": "none",
                    "answer_style": "brief_operational",
                },
            )
        )
    return quiet_hours


def _quiet_hours_from_hints(
    config: PersonalityConfig,
    hinted_conditions: list[Any],
) -> list[dict[str, Any]]:
    normalized_hints = {str(h).strip() for h in hinted_conditions if str(h).strip()}
    return [
        _quiet_hour_record(quiet_hour.condition, quiet_hour.clamps)
        for quiet_hour in config.quiet_hours
        if quiet_hour.condition in normalized_hints
    ]


def _quiet_hour_record(condition: str, clamps: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition": condition,
        "clamps": dict(clamps),
    }


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
        """Build a per-turn persona behavior plan."""
        turn = _turn_planning_context(
            config=config,
            user_message=user_message,
            tools=tools,
            relationship=relationship,
            milestones=milestones,
        )
        register_name = self._select_register(
            config=turn.config,
            user_message=turn.user_message,
            scenario=scenario,
            task_category=task_category,
            tools=turn.tools,
        )
        state = self._select_turn_plan_state(
            turn=turn,
            register_name=register_name,
            scenario=scenario,
            task_category=task_category,
            emotional_state=emotional_state,
        )
        return self._assemble_turn_plan(turn, state)

    def _assemble_turn_plan(
        self,
        turn: _TurnPlanningContext,
        state: _TurnPlanState,
    ) -> PersonaTurnPlan:
        return self._build_turn_plan(
            config=turn.config,
            register_name=state.register_name,
            register=state.register,
            situation_strength=state.situation_strength,
            quiet_hours=state.quiet_hours,
            persona_intensity=state.persona_intensity,
            active_triggers=state.active_triggers,
            active_layer=state.active_layer,
            layer_modifiers=state.layer_modifiers,
            dynamic_modulations=state.dynamic_modulations,
            user_message=turn.user_message,
        )

    def _select_turn_plan_state(
        self,
        *,
        turn: _TurnPlanningContext,
        register_name: str,
        scenario: str,
        task_category: str,
        emotional_state: Any | None,
    ) -> _TurnPlanState:
        register = turn.config.registers.get(register_name) or Register()
        active_layer, layer_modifiers, dynamic_modulations = self._select_expression_state(
            turn,
            emotional_state=emotional_state,
        )
        active_triggers = self._select_turn_triggers(
            turn=turn,
            register=register_name,
            scenario=scenario,
            task_category=task_category,
        )
        quiet_hours = self._select_turn_quiet_hours(
            turn=turn,
            register=register_name,
            scenario=scenario,
            task_category=task_category,
        )
        persona_intensity, situation_strength = self._select_turn_strengths(
            register=register_name,
            active_triggers=active_triggers,
            quiet_hours=quiet_hours,
        )
        return _TurnPlanState(
            register_name=register_name,
            register=register,
            situation_strength=situation_strength,
            quiet_hours=quiet_hours,
            persona_intensity=persona_intensity,
            active_triggers=active_triggers,
            active_layer=active_layer,
            layer_modifiers=layer_modifiers,
            dynamic_modulations=dynamic_modulations,
        )

    def _select_expression_state(
        self,
        turn: _TurnPlanningContext,
        *,
        emotional_state: Any | None,
    ) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
        active_layer, layer_modifiers = self._select_layer(
            config=turn.config,
            relationship=turn.relationship,
            milestones=turn.milestones,
        )
        dynamic_modulations = self._dynamic_modulations(
            config=turn.config,
            emotional_state=emotional_state,
        )
        return active_layer, layer_modifiers, dynamic_modulations

    def _select_turn_strengths(
        self,
        *,
        register: str,
        active_triggers: list[ActivePersonaTrigger],
        quiet_hours: list[dict[str, Any]],
    ) -> tuple[int, str]:
        persona_intensity = self._persona_intensity(
            register=register,
            active_triggers=active_triggers,
            quiet_hours=quiet_hours,
        )
        situation_strength = self._resolve_situation_strength(
            register=register,
            active_triggers=active_triggers,
        )
        return persona_intensity, situation_strength

    def _select_turn_triggers(
        self,
        *,
        turn: _TurnPlanningContext,
        register: str,
        scenario: str,
        task_category: str,
    ) -> list[ActivePersonaTrigger]:
        return self._select_active_triggers_for_turn(
            config=turn.config,
            user_message=turn.user_message,
            register=register,
            scenario=scenario,
            task_category=task_category,
            tools=turn.tools,
        )

    def _select_turn_quiet_hours(
        self,
        *,
        turn: _TurnPlanningContext,
        register: str,
        scenario: str,
        task_category: str,
    ) -> list[dict[str, Any]]:
        return self._select_quiet_hours(
            config=turn.config,
            user_message=turn.user_message,
            register=register,
            scenario=scenario,
            task_category=task_category,
            tools=turn.tools,
        )

    def _select_active_triggers_for_turn(
        self,
        *,
        config: PersonalityConfig,
        user_message: str,
        register: str,
        scenario: str,
        task_category: str,
        tools: list[str],
    ) -> list[ActivePersonaTrigger]:
        return self._select_triggers(
            config=config,
            user_message=user_message,
            register=register,
            scenario=scenario,
            task_category=task_category,
            tools=tools,
        )

    def _build_turn_plan(
        self,
        *,
        config: PersonalityConfig,
        register_name: str,
        register: Register,
        situation_strength: str,
        quiet_hours: list[dict[str, Any]],
        persona_intensity: int,
        active_triggers: list[ActivePersonaTrigger],
        active_layer: str | None,
        layer_modifiers: dict[str, Any],
        dynamic_modulations: dict[str, Any],
        user_message: str,
    ) -> PersonaTurnPlan:
        register_names, register_is_hard_clamp = self._select_register_candidates(
            config=config,
            user_message=user_message,
            fallback_register=register_name,
        )
        return PersonaTurnPlan(
            persona_name=config.name,
            identity_core=asdict(config.identity_core),
            idiolect=asdict(config.idiolect),
            register=register_name,
            register_description=register.description,
            register_behavior=register.behavior,
            register_candidates=[
                PersonaRegisterCandidate(
                    register=name,
                    description=(config.registers.get(name) or Register()).description,
                    behavior=(config.registers.get(name) or Register()).behavior,
                    reason=(
                        "required safety or explicit seriousness clamp"
                        if register_is_hard_clamp
                        else "retrieved expression candidate"
                    ),
                )
                for name in register_names
            ],
            register_is_hard_clamp=register_is_hard_clamp,
            situation_strength=situation_strength,
            quiet_hours=quiet_hours,
            persona_intensity=persona_intensity,
            active_triggers=active_triggers,
            active_layer=active_layer,
            layer_modifiers=layer_modifiers,
            dynamic_modulations=dynamic_modulations,
            selected_examples=self._select_examples(register=register, user_message=user_message),
        )

    def _select_register_candidates(
        self,
        *,
        config: PersonalityConfig,
        user_message: str,
        fallback_register: str,
    ) -> tuple[list[str], bool]:
        """Retrieve a bounded candidate set without pre-classifying the turn."""

        if self._contains_any(user_message, _CRISIS_TERMS):
            return [fallback_register], True
        if self._contains_any(user_message, _SERIOUS_TERMS):
            return (
                self._available_registers(
                    config,
                    ("analysis", "task", fallback_register),
                    limit=2,
                ),
                True,
            )

        candidates = [fallback_register]
        if self._contains_any(user_message, _EMOTIONAL_TERMS):
            candidates.extend(("emotional", "casual", "chat"))
        elif self._contains_any(user_message, _DOMAIN_TERMS):
            candidates.extend(("analysis", "task", "casual"))
        elif self._contains_any(user_message, _PLAY_TERMS):
            candidates.extend(("casual", "chat"))
        else:
            candidates.extend(("casual", "chat", "analysis"))
        return self._available_registers(config, tuple(candidates), limit=3), False

    @staticmethod
    def _available_registers(
        config: PersonalityConfig,
        candidates: tuple[str, ...],
        *,
        limit: int,
    ) -> list[str]:
        selected: list[str] = []
        for candidate in candidates:
            if candidate in config.registers and candidate not in selected:
                selected.append(candidate)
            if len(selected) >= limit:
                break
        if not selected:
            selected.append(next(iter(config.registers), candidates[0]))
        return selected

    @staticmethod
    def _resolve_situation_strength(
        *,
        register: str,
        active_triggers: list["ActivePersonaTrigger"],
    ) -> str:
        if register == "crisis":
            return "crisis"
        return "strong" if active_triggers else "ordinary"

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
        if self._contains_any(user_message, _SERIOUS_TERMS):
            return self._first_available(config, ("analysis", "task", "chat", "casual"))
        normalized_scenario = str(scenario or "").lower()
        normalized_task_category = str(task_category or "").lower()
        if normalized_scenario in {"analysis"} or "analysis" in normalized_task_category:
            return self._first_available(config, ("analysis", "task", "chat", "casual"))
        if (
            tools
            or normalized_scenario in {"task", "code", "debug"}
            or any(
                term in normalized_task_category for term in ("code", "debug", "execution", "task")
            )
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
        tools: list[str],
    ) -> list[ActivePersonaTrigger]:
        return self._select_keyword_triggers(
            config=config,
            user_message=user_message,
            register=register,
            scenario=scenario,
            task_category=task_category,
            tools=tools,
        )

    def _select_keyword_triggers(
        self,
        *,
        config: PersonalityConfig,
        user_message: str,
        register: str,
        scenario: str,
        task_category: str,
        tools: list[str],
    ) -> list[ActivePersonaTrigger]:
        selected = []
        for trigger in config.signature_triggers:
            trigger_id = str(trigger.trigger_id or "").strip()
            if not trigger_id:
                continue
            if self._should_suppress_trigger_for_execution(trigger_id=trigger_id, tools=tools):
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
            selected.append(_active_trigger(trigger_id, trigger, reason=reason))
            if len(selected) >= 2:
                break
        return selected

    @staticmethod
    def _select_examples(*, register: Register, user_message: str, limit: int = 2) -> list[str]:
        """Pick the most relevant few-shot examples for the current turn.

        Previously this was a flat ``register.examples[:2]`` — first-N
        regardless of what the user said, so personas authored with 5-7
        examples per register saw the same 2 every time. Now examples are
        scored by token overlap against the user message (reusing the same
        Chinese/English tokenizer the trigger condition matcher uses), and
        the top ``limit`` win. Falls back to declaration order when no
        examples overlap (or no user message) so the behaviour is stable
        and deterministic.
        """
        examples = [
            example for example in register.examples if isinstance(example, str) and example.strip()
        ]
        if len(examples) <= limit:
            return list(examples)
        message_terms = set(_tokenize_for_overlap(user_message))
        if not message_terms:
            return list(examples[:limit])
        scored: list[tuple[int, int, str]] = []
        for index, example in enumerate(examples):
            example_terms = set(_tokenize_for_overlap(example))
            overlap = len(message_terms & example_terms)
            # Sort key: higher overlap wins, earlier declaration breaks ties.
            scored.append((-overlap, index, example))
        scored.sort()
        if scored[0][0] == 0:
            # No example overlapped at all — keep declaration order so we
            # do not arbitrarily re-rank examples that have nothing to say
            # about this turn.
            return list(examples[:limit])
        return [example for _, _, example in scored[:limit]]

    @staticmethod
    def _should_suppress_trigger_for_execution(*, trigger_id: str, tools: list[str]) -> bool:
        if not tools:
            return False
        normalized_id = trigger_id.lower()
        always_allowed = {
            "crisis",
            "emotional",
            "emotional_resonance",
            "boundary_violation",
            "safety",
        }
        return normalized_id not in always_allowed

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
        if normalized_id in {"value_topic", "judgment"} and self._contains_any(
            user_message, _VALUE_TERMS
        ):
            return "user asks for judgment or stance"
        if normalized_id in {"emotional_resonance", "emotional"} and self._contains_any(
            user_message, _EMOTIONAL_TERMS
        ):
            return "user emotional state is salient"
        if self._condition_overlap(user_message, activates_when):
            return "persona trigger condition overlaps the user turn"
        _ = (scenario, task_category)
        return ""

    @staticmethod
    def _trigger_intensity(levels: dict[str, str]) -> str:
        return _trigger_intensity(levels)

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
        quiet_hours = _built_in_quiet_hours(register=register, tools=tools)
        quiet_hours.extend(self._fallback_quiet_hours(config, user_message))
        _ = (scenario, task_category)
        return quiet_hours

    def _fallback_quiet_hours(
        self,
        config: PersonalityConfig,
        user_message: str,
    ) -> list[dict[str, Any]]:
        quiet_hours = []
        if self._contains_any(user_message, _SERIOUS_TERMS):
            quiet_hours.append(
                {
                    "condition": "user_requested_seriousness",
                    "clamps": {
                        "persona_intensity_max": 1,
                        "jokes": "none",
                    },
                }
            )
        for quiet_hour in config.quiet_hours:
            if self._condition_overlap(user_message, quiet_hour.condition):
                quiet_hours.append(_quiet_hour_record(quiet_hour.condition, quiet_hour.clamps))
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
        """Pick the deepest persona layer whose unlock conditions are all
        currently satisfied.

        Strictly re-evaluated every turn from the current relationship +
        milestone snapshot, so a trust drop or a milestone breach naturally
        regresses to a shallower layer instead of latching onto a
        previously-unlocked one. The previous implementation iterated layers
        in JSON declaration order and kept the last match, which made the
        result depend on author-order (e.g. an AI-generated config that
        emitted ``[revealed, crack, surface]`` would always pick ``surface``
        even at high trust). Depth score makes the choice order-independent:
        the strictest matching unlock gate wins.
        """
        trust = float(relationship.get("trust_level", 0.0) or 0.0)
        interaction_count = int(
            relationship.get("interaction_count", relationship.get("total_interactions", 0)) or 0
        )
        milestone_keys = {
            str(item.get("key") or item.get("title") or item.get("id") or "").strip()
            for item in milestones
            if isinstance(item, dict)
        }

        best_score = -1.0
        best_layer = None
        for index, layer in enumerate(config.persona_layers):
            condition = layer.unlock_condition or {}
            trust_required = condition.get("trust_level_gte")
            if trust_required is not None and trust < float(trust_required):
                continue
            interaction_required = condition.get("interaction_count_gte")
            if interaction_required is not None and interaction_count < int(interaction_required):
                continue
            milestone_required = str(condition.get("milestone_required") or "").strip()
            if milestone_required and milestone_required not in milestone_keys:
                continue
            # All gates pass. Score this layer by how exclusive its unlock is.
            # Trust threshold dominates because it is the canonical depth
            # signal in the persona runtime architecture; interaction count
            # and milestone presence act as secondary tie-breakers. A layer
            # with no unlock_condition (e.g. surface) scores 0 and acts as
            # the safety baseline. JSON order is used only to break exact
            # ties (later declaration wins, matching the legacy default).
            depth_score = float(trust_required or 0.0)
            depth_score += float(interaction_required or 0) / 1000.0
            if milestone_required:
                depth_score += 0.01
            # Tie-breaker: later JSON index wins on exact equality.
            depth_score += index * 1e-9
            if depth_score > best_score:
                best_score = depth_score
                best_layer = layer

        if best_layer is None:
            return None, {}
        return (best_layer.layer_id or None, dict(best_layer.modifiers))

    @staticmethod
    def _dynamic_modulations(
        *,
        config: PersonalityConfig,
        emotional_state: Any | None,
    ) -> dict[str, Any]:
        """Map current emotional state to active dynamic_state_rules entries.

        Recognised keys (all optional in the persona JSON):
        - ``low_energy``    fires when energy < 0.35
        - ``high_stress``   fires when stress > 0.70
        - ``positive_mood`` fires when mood is one of {positive, happy, good, excited}
        - ``flow_state``    fires when focus_state == "flow"
                            (computed as energy > 0.8 + stress < 0.3)
        - ``distracted_state`` fires when focus_state == "distracted"
                            (computed as stress > 0.8 — note this is a stricter
                            threshold than high_stress so both can co-fire)
        """
        if emotional_state is None:
            return {}
        state = (
            asdict(emotional_state)
            if is_dataclass(emotional_state)
            else dict(emotional_state or {})
        )
        energy = float(state.get("energy_level", 0.7) or 0.7)
        stress = float(state.get("stress_level", 0.2) or 0.2)
        mood = str(state.get("current_mood") or state.get("mood") or "neutral").lower()
        focus = str(state.get("focus_state") or "normal").lower()
        active_rules: dict[str, str] = {}
        if energy < 0.35 and "low_energy" in config.dynamic_state_rules:
            active_rules["low_energy"] = config.dynamic_state_rules["low_energy"]
        if stress > 0.70 and "high_stress" in config.dynamic_state_rules:
            active_rules["high_stress"] = config.dynamic_state_rules["high_stress"]
        if (
            mood in {"positive", "happy", "good", "excited"}
            and "positive_mood" in config.dynamic_state_rules
        ):
            active_rules["positive_mood"] = config.dynamic_state_rules["positive_mood"]
        if focus == "flow" and "flow_state" in config.dynamic_state_rules:
            active_rules["flow_state"] = config.dynamic_state_rules["flow_state"]
        if focus == "distracted" and "distracted_state" in config.dynamic_state_rules:
            active_rules["distracted_state"] = config.dynamic_state_rules["distracted_state"]
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
    cjk_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    cjk_terms: list[str] = []
    for chunk in cjk_chunks:
        cjk_terms.append(chunk)
        for width in (2, 3, 4):
            cjk_terms.extend(
                chunk[index : index + width] for index in range(0, max(len(chunk) - width + 1, 0))
            )
    return [*latin_terms, *cjk_terms]


__all__ = [
    "ActivePersonaTrigger",
    "PersonaRegisterCandidate",
    "PersonaTurnPlan",
    "PersonaTurnPlanner",
]
