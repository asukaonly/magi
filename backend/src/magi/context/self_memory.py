"""Self-memory and profile-memory prompt context assembly."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..personality.feature_flags import get_personality_feature_flags
from ..personality.loader import PersonalityConfig
from ..personality.persona_journal_service import PersonaJournalService
from ..personality.turn_planner import (
    PersonaTurnPlan,
    PersonaTurnPlanner,
)
from .schema import (
    ProfileMemoryContext,
    RetrievalMemoryContext,
    SelfMemoryContext,
)
from .user_profile_service import UserProfileService


class PromptSelfMemoryMixin:
    """Build self-memory and user profile prompt context blocks."""

    persona_journal_service: PersonaJournalService | None
    user_profile_service: UserProfileService | None

    async def _build_self_memory_context(
        self,
        *,
        self_memory,
        user_id: str,
        user_message: str,
        task_category: str,
        scenario: str,
        selected_tools: List[str],
        retrieved_memory_payload: Optional[Dict[str, Any]],
        persona_turn_plan: "Optional[PersonaTurnPlan]" = None,
        persona_name: str,
    ) -> SelfMemoryContext:
        payload = retrieved_memory_payload or {}
        preference_memory = payload.get("preference_memory", {})
        if not isinstance(preference_memory, dict):
            preference_memory = {}
        preference_memory = dict(preference_memory)
        preference_memory.pop("user_preferences", None)

        retrieval_memory = RetrievalMemoryContext(
            l0_workbench=list(payload.get("l0_workbench", [])),
            l2_entity_cards=list(payload.get("l2_entity_cards", [])),
            l3_reflection_memory=list(payload.get("l3_reflection_memory", [])),
            l4_procedural_memory=list(payload.get("l4_procedural_memory", [])),
            preference_memory=preference_memory,
        )

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

        if persona_turn_plan is None:
            persona_turn_plan = await self._build_persona_turn_plan(
                self_memory=self_memory,
                user_id=user_id,
                user_message=user_message,
                task_category=task_category,
                scenario=scenario,
                selected_tools=selected_tools,
            )

        return SelfMemoryContext(
            retrieval_memory=retrieval_memory,
            persona_turn_plan=persona_turn_plan,
            persona_journal_entries=journal_entries,
        )

    async def _build_persona_turn_plan(
        self,
        *,
        self_memory,
        user_id: str,
        user_message: str,
        task_category: str,
        scenario: str,
        selected_tools: List[str],
    ) -> PersonaTurnPlan:
        config = PersonalityConfig()
        emotional_state = None
        relationship: Dict[str, Any] = {}
        milestones: List[Dict[str, Any]] = []

        if self_memory is not None:
            if hasattr(self_memory, "get_core_personality"):
                config = await self_memory.get_core_personality() or config
            if hasattr(self_memory, "get_emotional_state"):
                emotional_state = await self_memory.get_emotional_state()
            if user_id and hasattr(self_memory, "get_relationship"):
                relationship = await self_memory.get_relationship(user_id) or {}
            if hasattr(self_memory, "get_milestones"):
                milestones = await self_memory.get_milestones(limit=200) or []

        plan = PersonaTurnPlanner().build_plan(
            config=config,
            user_message=user_message,
            scenario=scenario,
            task_category=task_category,
            tools=selected_tools,
            relationship=relationship,
            emotional_state=emotional_state,
            milestones=milestones,
        )

        return plan

    async def _build_profile_memory_context(self, *, self_memory, user_id: str) -> ProfileMemoryContext:
        user_name = ""
        preferences: Dict[str, Any] = {}
        features = get_personality_feature_flags()

        if self.user_profile_service is not None and user_id:
            fetched_name = await self.user_profile_service.get_display_name(user_id)
            if fetched_name and fetched_name != "unknown":
                user_name = fetched_name
            preferences = await self.user_profile_service.get_preference_summary(user_id)
            prompt_summary = await self.user_profile_service.get_portrait_prompt_summary(user_id)
        else:
            prompt_summary = []

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
            prompt_summary=prompt_summary,
            recent_emotion=recent_emotion,
        )


__all__ = ["PromptSelfMemoryMixin"]
