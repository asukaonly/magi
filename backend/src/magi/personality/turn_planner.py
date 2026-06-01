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


@dataclass(slots=True, frozen=True)
class PersonaRoutingHint:
    """Per-persona routing decisions supplied by the unified ContextDecider.

    Carried separately from ``ContextDecision`` so the personality and context
    layers do not need a structural dependency on ``tools/context_routing``.
    Build one from a ContextDecision at the chat-coordinator boundary; pass
    it through context-assembly layers to the planner.
    """

    register: str | None = None
    active_trigger_ids: tuple[str, ...] = ()
    situation_strength: str = "ordinary"
    quiet_hour_hints: tuple[str, ...] = ()


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
        routing_hint: "PersonaRoutingHint | None" = None,
        previous_trigger_ids: list[str] | None = None,
    ) -> PersonaTurnPlan:
        """Build a per-turn persona behavior plan.

        ``routing_hint`` carries the unified ContextDecider's per-persona
        routing output (register / active_trigger_ids / quiet_hour_hints).
        When the hint provides a field, the planner consumes it directly
        instead of running its built-in keyword classifier. When the hint
        is None or a field is missing, the keyword fallback runs so the
        planner remains usable in tests, offline contexts, and any code
        path that has not yet been wired through ContextDecider.
        """
        persona_config = config or PersonalityConfig()
        normalized_message = str(user_message or "")
        selected_tools = [str(tool) for tool in (tools or []) if str(tool).strip()]
        register_name = self._select_register(
            config=persona_config,
            user_message=normalized_message,
            scenario=scenario,
            task_category=task_category,
            tools=selected_tools,
            routing_hint=routing_hint,
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
            tools=selected_tools,
            routing_hint=routing_hint,
        )
        if not active_triggers and previous_trigger_ids:
            # No new trigger fired this turn but something fired last turn.
            # Carry the emotional state forward one hop with reduced intensity
            # so the persona does not snap from "still angry" to "neutral"
            # between adjacent turns. Bounded to a single hop because only
            # NEW (non-carryover) trigger_ids should be written back into
            # ``emotional_state.recent_active_trigger_ids`` by the caller.
            active_triggers = self._build_carryover_triggers(
                config=persona_config,
                previous_trigger_ids=previous_trigger_ids,
                tools=selected_tools,
            )
        quiet_hours = self._select_quiet_hours(
            config=persona_config,
            user_message=normalized_message,
            register=register_name,
            scenario=scenario,
            task_category=task_category,
            tools=selected_tools,
            routing_hint=routing_hint,
        )
        persona_intensity = self._persona_intensity(
            register=register_name,
            active_triggers=active_triggers,
            quiet_hours=quiet_hours,
        )
        situation_strength = self._resolve_situation_strength(
            register=register_name,
            active_triggers=active_triggers,
            routing_hint=routing_hint,
        )

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
            selected_examples=self._select_examples(register=register, user_message=normalized_message),
        )

    @staticmethod
    def _resolve_situation_strength(
        *,
        register: str,
        active_triggers: list["ActivePersonaTrigger"],
        routing_hint: "PersonaRoutingHint | None",
    ) -> str:
        hinted = getattr(routing_hint, "situation_strength", "") if routing_hint else ""
        if isinstance(hinted, str) and hinted.strip().lower() in {"ordinary", "strong", "crisis"}:
            return hinted.strip().lower()
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
        routing_hint: "PersonaRoutingHint | None" = None,
    ) -> str:
        # Unified router (LLM) decides the register when wired through
        # ContextDecider. Keyword fallback below is the offline/testing path
        # and the safety net when the LLM omits or invalidates the field.
        hinted = getattr(routing_hint, "register", None) if routing_hint else None
        if isinstance(hinted, str) and hinted.strip().lower() in {
            "casual", "chat", "task", "analysis", "emotional", "crisis"
        }:
            normalized_hint = hinted.strip().lower()
            # The product enum is the same 5 across personas, but persona
            # presets may have inherited a "chat" alias. Resolve to whichever
            # actually exists in this persona's register dict.
            if normalized_hint == "casual":
                return self._first_available(config, ("casual", "chat"))
            if normalized_hint == "chat":
                return self._first_available(config, ("chat", "casual"))
            return self._first_available(
                config,
                (normalized_hint, "task", "analysis", "chat", "casual"),
            )

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
        tools: list[str],
        routing_hint: "PersonaRoutingHint | None" = None,
    ) -> list[ActivePersonaTrigger]:
        hinted_ids = list(getattr(routing_hint, "active_trigger_ids", []) or []) if routing_hint else []
        if hinted_ids:
            # Unified-router path: trigger IDs are entirely config-driven. The
            # planner only looks up the matching SignatureTrigger objects in
            # the persona config; it does not maintain a hardcoded ID
            # whitelist anymore. New trigger IDs in JSON Just Work.
            by_id: dict[str, SignatureTrigger] = {
                str(t.trigger_id or "").strip(): t
                for t in config.signature_triggers
                if str(t.trigger_id or "").strip()
            }
            selected: list[ActivePersonaTrigger] = []
            for raw_id in hinted_ids:
                trigger_id = str(raw_id or "").strip()
                if not trigger_id:
                    continue
                trigger = by_id.get(trigger_id)
                if trigger is None:
                    # LLM hallucinated an ID outside the menu; ignore and rely
                    # on its other choices.
                    continue
                if self._should_suppress_trigger_for_execution(trigger_id=trigger_id, tools=tools):
                    continue
                selected.append(
                    ActivePersonaTrigger(
                        trigger_id=trigger_id,
                        intensity=self._trigger_intensity(trigger.intensity_levels),
                        behavior_shift=trigger.behavior_shift,
                        reason="routing_hint",
                    )
                )
                if len(selected) >= 2:
                    break
            return selected

        # Keyword fallback path: no LLM hint present (offline / tests / not
        # yet wired). The hand-rolled matcher recognizes a handful of well-
        # known trigger IDs and otherwise falls back to bag-of-words overlap
        # against ``activates_when``. Less accurate than the LLM path but
        # safe for tests.
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

    def _build_carryover_triggers(
        self,
        *,
        config: PersonalityConfig,
        previous_trigger_ids: list[str],
        tools: list[str],
    ) -> list[ActivePersonaTrigger]:
        """Resurrect last turn's triggers at one-notch-lower intensity.

        Carryover is bounded: the caller writes only NEW trigger_ids (those
        with reason != "carryover") back into emotional state, so a carryover
        does not propagate to a third turn unless something fresh fires
        between them. The execution suppression rule still applies — task
        and analysis turns drop carryover absurdity / hostility just like
        they drop fresh ones.
        """
        by_id: dict[str, SignatureTrigger] = {
            str(t.trigger_id or "").strip(): t
            for t in config.signature_triggers
            if str(t.trigger_id or "").strip()
        }
        selected: list[ActivePersonaTrigger] = []
        for raw_id in previous_trigger_ids:
            trigger_id = str(raw_id or "").strip()
            if not trigger_id:
                continue
            trigger = by_id.get(trigger_id)
            if trigger is None:
                continue
            if self._should_suppress_trigger_for_execution(trigger_id=trigger_id, tools=tools):
                continue
            selected.append(
                ActivePersonaTrigger(
                    trigger_id=trigger_id,
                    intensity=self._downgrade_intensity(trigger.intensity_levels),
                    behavior_shift=trigger.behavior_shift,
                    reason="carryover",
                )
            )
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
        examples = [example for example in register.examples if isinstance(example, str) and example.strip()]
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
    def _downgrade_intensity(levels: dict[str, str]) -> str:
        """Pick the quietest available intensity level for a carryover trigger."""
        for preferred in ("low", "mild", "mid", "medium", "high", "peak"):
            if preferred in levels:
                return preferred
        return "low"

    @staticmethod
    def _should_suppress_trigger_for_execution(*, trigger_id: str, tools: list[str]) -> bool:
        if not tools:
            return False
        normalized_id = trigger_id.lower()
        always_allowed = {"crisis", "emotional", "emotional_resonance", "boundary_violation", "safety"}
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
        routing_hint: "PersonaRoutingHint | None" = None,
    ) -> list[dict[str, Any]]:
        # Register-derived built-in clamps are deterministic and run on every
        # turn regardless of routing source: task/analysis tighten focus,
        # emotional softens, crisis zeros out performance.
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
        if register == "emotional":
            quiet_hours.append({
                "condition": "emotional_support",
                "clamps": {
                    "persona_intensity_max": 1,
                    "sarcasm": "none_to_light",
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

        # Persona-defined quiet-hour conditions. Two ways to pick them:
        # 1) Unified router supplied condition strings that match this
        #    persona's configured quiet_hours.
        # 2) Keyword fallback when there is no LLM hint.
        hinted_conditions = list(getattr(routing_hint, "quiet_hour_hints", []) or []) if routing_hint else []
        if hinted_conditions:
            normalized_hints = {str(h).strip() for h in hinted_conditions if str(h).strip()}
            for quiet_hour in config.quiet_hours:
                if quiet_hour.condition in normalized_hints:
                    quiet_hours.append({
                        "condition": quiet_hour.condition,
                        "clamps": dict(quiet_hour.clamps),
                    })
        else:
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
        state = asdict(emotional_state) if is_dataclass(emotional_state) else dict(emotional_state or {})
        energy = float(state.get("energy_level", 0.7) or 0.7)
        stress = float(state.get("stress_level", 0.2) or 0.2)
        mood = str(state.get("current_mood") or state.get("mood") or "neutral").lower()
        focus = str(state.get("focus_state") or "normal").lower()
        active_rules: dict[str, str] = {}
        if energy < 0.35 and "low_energy" in config.dynamic_state_rules:
            active_rules["low_energy"] = config.dynamic_state_rules["low_energy"]
        if stress > 0.70 and "high_stress" in config.dynamic_state_rules:
            active_rules["high_stress"] = config.dynamic_state_rules["high_stress"]
        if mood in {"positive", "happy", "good", "excited"} and "positive_mood" in config.dynamic_state_rules:
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
            cjk_terms.extend(chunk[index : index + width] for index in range(0, max(len(chunk) - width + 1, 0)))
    return [*latin_terms, *cjk_terms]


__all__ = [
    "ActivePersonaTrigger",
    "PersonaRoutingHint",
    "PersonaTurnPlan",
    "PersonaTurnPlanner",
]
