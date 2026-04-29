"""Self-memory and profile-memory prompt context assembly."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from ..personality.feature_flags import get_personality_feature_flags
from ..personality.persona_journal_service import PersonaJournalService
from .schema import ProfileMemoryContext, RetrievalMemoryContext, SelfMemoryContext
from .user_profile_service import UserProfileService


class PromptSelfMemoryMixin:
    """Build self-memory and user profile prompt context blocks."""

    scenario_prompts_store: Any
    persona_journal_service: PersonaJournalService | None
    user_profile_service: UserProfileService | None

    async def _build_self_memory_context(
        self,
        *,
        self_memory,
        user_id: str,
        task_category: str,
        retrieved_memory_payload: Optional[Dict[str, Any]],
        state_transition_override: Optional[str],
        scenario: str = "chat",
        persona_name: str = "default",
    ) -> SelfMemoryContext:
        persona_entity: Dict[str, Any] = {}
        dynamic_state: Dict[str, Any] = {}
        active_stp_trigger = ""
        active_stp_state_name = ""
        features = get_personality_feature_flags()
        state_transition_scope_enabled = str(scenario or "").strip() == "chat"

        if self_memory is not None:
            config = await self_memory.get_core_personality()
            if hasattr(config, "persona_entity"):
                try:
                    persona_entity = asdict(config.persona_entity)
                except Exception:
                    persona_entity = {"name": getattr(config, "name", "AI Assistant")}
            else:
                persona_entity = {"name": getattr(config, "name", "AI Assistant")}

            if features.state_memory_enabled:
                emotion = await self_memory.get_emotional_state()
                dynamic_state = {
                    "mood": getattr(emotion, "current_mood", "neutral"),
                    "mood_intensity": float(getattr(emotion, "mood_intensity", 0.5)),
                    "energy_level": float(getattr(emotion, "energy_level", 0.7)),
                    "stress_level": float(getattr(emotion, "stress_level", 0.2)),
                }
                if features.state_transition_enabled and state_transition_scope_enabled:
                    active_stp_trigger = getattr(emotion, "active_stp_trigger", "") or ""
                    active_stp_state_name = getattr(emotion, "active_stp_state_name", "") or ""

        user_pref_memory: Dict[str, Any] = {}
        if self.user_profile_service is not None and user_id:
            user_pref_memory = await self.user_profile_service.get_preference_summary(user_id)

        payload = retrieved_memory_payload or {}
        retrieval_memory = RetrievalMemoryContext(
            l0_workbench=list(payload.get("l0_workbench", [])),
            l2_entity_cards=list(payload.get("l2_entity_cards", [])),
            l3_reflection_memory=list(payload.get("l3_reflection_memory", [])),
            l4_procedural_memory=list(payload.get("l4_procedural_memory", [])),
            preference_memory={
                "user_preferences": user_pref_memory,
                **dict(payload.get("preference_memory", {})),
            },
        )

        scenario_prompt_text: Optional[str] = None
        if self.scenario_prompts_store:
            scenario_prompt_text = await self.scenario_prompts_store.get_prompt(persona_name, scenario)
            if not scenario_prompt_text:
                scenario_prompt_text = await self.scenario_prompts_store.get_prompt("default", scenario)

        active_layers = []
        if features.state_memory_enabled and features.deep_persona_enabled:
            active_layers = await self._evaluate_persona_layers(
                self_memory=self_memory,
                user_id=user_id,
            )

        stp_rules: List[Dict[str, str]] = []
        resolved_override = state_transition_override if state_transition_scope_enabled else None
        if self_memory is not None and features.state_transition_enabled and state_transition_scope_enabled:
            config = await self_memory.get_core_personality()
            if hasattr(config, "state_transition_protocol") and config.state_transition_protocol:
                for item in config.state_transition_protocol:
                    trigger_type = getattr(item, "trigger_type", "")
                    if not trigger_type:
                        continue
                    if active_stp_trigger and trigger_type != active_stp_trigger:
                        continue
                    rule: Dict[str, str] = {}
                    rule["trigger_type"] = trigger_type
                    condition = getattr(item, "trigger_condition", "")
                    if condition:
                        rule["trigger_condition"] = condition
                    shift = getattr(item, "behavior_shift", "")
                    if shift:
                        rule["behavior_shift"] = shift
                    stp_rules.append(rule)

            active_behavior_shift: Optional[str] = None
            if active_stp_trigger and active_stp_state_name and not resolved_override:
                resolved_override = active_stp_state_name
                for item in config.state_transition_protocol:
                    if getattr(item, "trigger_type", "") == active_stp_trigger:
                        active_behavior_shift = getattr(item, "behavior_shift", "") or None
                        break
        else:
            active_behavior_shift = None

        journal_entries: List[Dict[str, Any]] = []
        if self.persona_journal_service is not None:
            try:
                entries = await self.persona_journal_service.get_recent_entries(
                    persona_name=persona_name,
                    limit=3,
                )
                journal_entries = [
                    {"content": entry.content, "timestamp": entry.timestamp}
                    for entry in entries
                ]
            except Exception:
                pass

        return SelfMemoryContext(
            persona_entity=persona_entity,
            dynamic_state=dynamic_state,
            retrieval_memory=retrieval_memory,
            state_transition_override=resolved_override,
            state_transition_behavior_shift=active_behavior_shift if active_stp_trigger else None,
            state_transition_rules=stp_rules,
            scenario_prompt=scenario_prompt_text,
            active_persona_layers=active_layers,
            persona_journal_entries=journal_entries,
        )

    async def _evaluate_persona_layers(
        self,
        *,
        self_memory,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """Evaluate which persona layers are unlocked based on trust and milestones."""
        if self_memory is None:
            return []

        config = await self_memory.get_core_personality()
        if not hasattr(config, "persona_layers") or not config.persona_layers:
            return []

        relation = {}
        if user_id:
            relation = await self_memory.get_relationship(user_id) or {}

        trust_level = float(relation.get("trust_level", 0.0))
        total_interactions = int(relation.get("total_interactions", 0))

        milestone_titles: set = set()
        try:
            milestones = await self_memory.get_milestones(limit=200)
            milestone_titles = {m.get("title", "") for m in milestones if isinstance(m, dict)}
        except Exception:
            pass

        active_layers: List[Dict[str, Any]] = []
        for layer in config.persona_layers:
            layer_id = getattr(layer, "layer_id", "")
            condition = getattr(layer, "unlock_condition", None)

            if layer_id == "surface" or condition is None:
                continue

            trust_gate = condition.get("trust_level_gte", 0.0) if isinstance(condition, dict) else 0.0
            if trust_level < trust_gate:
                continue

            interaction_gate = condition.get("interaction_count_gte", 0) if isinstance(condition, dict) else 0
            if total_interactions < interaction_gate:
                continue

            milestone_req = condition.get("milestone_required") if isinstance(condition, dict) else None
            if milestone_req and milestone_req not in milestone_titles:
                continue

            layer_data: Dict[str, Any] = {"layer_id": layer_id}
            override = getattr(layer, "persona_override", None)
            if override:
                layer_data["persona_override"] = override
            hints = getattr(layer, "behavior_hints", None)
            if hints:
                layer_data["behavior_hints"] = hints
            active_layers.append(layer_data)

        return active_layers

    async def _build_profile_memory_context(self, *, self_memory, user_id: str) -> ProfileMemoryContext:
        user_name = ""
        preferences: Dict[str, Any] = {}
        features = get_personality_feature_flags()

        if self.user_profile_service is not None and user_id:
            fetched_name = await self.user_profile_service.get_display_name(user_id)
            if fetched_name and fetched_name != "unknown":
                user_name = fetched_name
            preferences = await self.user_profile_service.get_preference_summary(user_id)

        relation: Dict[str, Any] = {}
        if self_memory is not None and user_id and features.state_memory_enabled:
            relation = await self_memory.get_relationship(user_id) or {}

        recent_emotion: Dict[str, Any] = {}
        if relation:
            sentiment = float(relation.get("sentiment_score", 0.0))
            trust = float(relation.get("trust_level", 0.5))

            if sentiment >= 0.3:
                emotion_label = "positive"
            elif sentiment <= -0.3:
                emotion_label = "negative"
            else:
                emotion_label = "neutral"

            if trust >= 0.7:
                trust_label = "high"
            elif trust >= 0.4:
                trust_label = "medium"
            else:
                trust_label = "low"

            recent_emotion = {
                "sentiment_score": sentiment,
                "emotion_label": emotion_label,
                "trust_level": trust,
                "trust_label": trust_label,
            }

        return ProfileMemoryContext(
            user_id=user_id,
            user_name=user_name,
            user_preferences=preferences,
            recent_emotion=recent_emotion,
        )


__all__ = ["PromptSelfMemoryMixin"]