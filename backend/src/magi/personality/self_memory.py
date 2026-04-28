"""
Internal note.

Internal note.

Internal note.
Internal note.
Internal note.
Internal note.
Internal note.
Internal note.
"""
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import asdict

from .models import (
    EmotionalState,
)
from .loader import PersonalityConfig
from .behavior_evolution import BehaviorEvolutionEngine, SatisfactionLevel
from .emotional_state import EmotionalStateEngine, InteractionOutcome, EngagementLevel
from .growth_memory import GrowthMemoryEngine, InteractionType, MilestoneType
from .interaction_analyzer import InteractionAnalysis
from ..utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)


# ===== Unified Management Class =====

class SelfMemory:
    """
    Internal note.

    Internal note.
    """

    def __init__(
        self,
        personality_name: str = "default",
        db_path: str = None,
        enable_evolution: bool = True,
        *,
        persona_id: str = "",
        personality_config: Optional[PersonalityConfig] = None,
    ):
        """
        Internal note.

        Args:
            personality_name: Personality name
            Internal note.
            enable_evolution: is notEnablepersonalityevolution
            persona_id: Stable persona identity for scoping evolution data.
        """
        # Internal note.
        runtime_paths = get_runtime_paths()

        self.personality_name = personality_name
        self.persona_id = persona_id
        self.db_path = db_path or str(runtime_paths.self_memory_db_path)
        self.enable_evolution = enable_evolution

        self._behavior_engine: Optional[BehaviorEvolutionEngine] = None
        self._emotion_engine: Optional[EmotionalStateEngine] = None
        self._growth_engine: Optional[GrowthMemoryEngine] = None

        # cache - store parsed personality config
        self._personality_config: Optional[PersonalityConfig] = personality_config

    async def init(self):
        """initializeallcomponent"""
        # loadPersonality configuration
        await self._load_personality()

        if self.enable_evolution:
            # Internal note.
            runtime_paths = get_runtime_paths()
            behavior_db = str(runtime_paths.behavior_db_path)
            emotion_db = str(runtime_paths.emotional_db_path)
            growth_db = str(runtime_paths.growth_db_path)

            self._behavior_engine = BehaviorEvolutionEngine(behavior_db, persona_id=self.persona_id)
            self._emotion_engine = EmotionalStateEngine(emotion_db, persona_id=self.persona_id)
            self._growth_engine = GrowthMemoryEngine(growth_db, persona_id=self.persona_id)

            await self._behavior_engine.init()
            await self._emotion_engine.init()
            await self._growth_engine.init()

            # Record first-use milestone only if no milestones exist yet
            existing = await self._growth_engine.get_milestones(limit=1)
            if not existing:
                await self._growth_engine.record_milestone(
                    milestone_type=MilestoneType.FIRST_USE,
                    title=f"initialized as {self._personality_config.name}",
                    description=f"Personality {self.personality_name} loaded and initialized"
                )

        logger.info(f"SelfMemory initialized with personality: {self.personality_name}")

    async def _load_personality(self):
        """Load personality configuration from pre-loaded config, cache, or registry."""
        if self._personality_config is not None:
            logger.info(f"Using pre-loaded personality config: {self._personality_config.name}")
            return

        # Try the in-memory config cache or registry.
        from .active_persona import resolve_persona_config
        resolved = await resolve_persona_config(self.personality_name)
        if resolved is not None:
            self._personality_config = resolved
            logger.info(f"Loaded personality from registry/cache: {resolved.name}")
            return

        logger.warning(f"Personality {self.personality_name} not found in registry, using default")
        self._personality_config = PersonalityConfig()

    async def reload_personality(
        self,
        new_personality_name: str = None,
        personality_config: Optional[PersonalityConfig] = None,
    ):
        """
        Internal note.

        Args:
            Internal note.
        """
        old_personality_name = self.personality_name

        if new_personality_name:
            self.personality_name = new_personality_name

        # Use the explicitly passed config, or clear so _load_personality
        # re-resolves from cache / registry.
        self._personality_config = personality_config

        # Internal note.
        await self._load_personality()

        # Internal note.
        if self.enable_evolution and self._growth_engine and self._personality_config:
            from .growth_memory import MilestoneType
            await self._growth_engine.record_milestone(
                milestone_type=MilestoneType.FIRST_USE,
                title=f"Personality switched to {self._personality_config.name}",
                description=f"Reloaded personality configuration: {self.personality_name}"
            )

        name = self._personality_config.name if self._personality_config else "Unknown"
        logger.info(f"Personality reloaded: {old_personality_name} -> {self.personality_name} ({name})")

    # Internal note.

    async def get_core_personality(self) -> PersonalityConfig:
        """getcorePersonality configuration"""
        return self._personality_config or PersonalityConfig()

    # Internal note.

    async def record_task_outcome(
        self,
        task_id: str,
        task_category: str,
        user_satisfaction: SatisfactionLevel = SatisfactionLevel.NEUTRAL,
        clarification_count: int = 0,
        confirmation_count: int = 0,
        correction_count: int = 0,
        task_complexity: float = 0.5,
        task_duration: float = 0.0,
        accepted: bool = True,
    ):
        """Record task interaction result"""
        if self.enable_evolution and self._behavior_engine:
            await self._behavior_engine.record_task_outcome(
                task_id=task_id,
                task_category=task_category,
                user_satisfaction=user_satisfaction,
                clarification_count=clarification_count,
                confirmation_count=confirmation_count,
                correction_count=correction_count,
                task_complexity=task_complexity,
                task_duration=task_duration,
                accepted=accepted,
            )

    # Internal note.

    async def get_emotional_state(self) -> EmotionalState:
        """Get current emotional state"""
        if not self.enable_evolution or self._emotion_engine is None:
            return EmotionalState()

        return await self._emotion_engine.get_current_state()

    async def update_after_interaction(
        self,
        outcome: InteractionOutcome,
        user_engagement: EngagementLevel = EngagementLevel.MEDIUM,
        complexity: float = 0.5,
    ):
        """Update emotional state after interaction"""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.update_after_interaction(
                outcome=outcome,
                user_engagement=user_engagement,
                complexity=complexity,
            )

    async def update_stp_trigger(
        self,
        trigger_type: str,
        state_name: str,
    ) -> None:
        """Update the active STP trigger detected from interaction analysis."""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.update_stp_trigger(trigger_type, state_name)

    async def record_interaction(
        self,
        user_id: str,
        interaction_type: InteractionType,
        outcome: str = "neutral",
        sentiment: float = 0.0,
        notes: str = ""
    ):
        """Record interaction with user"""
        if self.enable_evolution and self._growth_engine:
            await self._growth_engine.record_interaction(
                user_id=user_id,
                interaction_type=interaction_type,
                outcome=outcome,
                sentiment=sentiment,
                notes=notes,
            )

    async def get_relationship(self, user_id: str) -> Optional[Dict]:
        """Get relationship with user"""
        if not self.enable_evolution or self._growth_engine is None:
            return None

        profile = await self._growth_engine.get_relationship(user_id)
        if profile:
            return asdict(profile)
        return None

    async def get_milestones(self, milestone_type: MilestoneType | None = None, limit: int = 100) -> List[Dict]:
        """Get milestones, optionally filtered by type."""
        if not self.enable_evolution or self._growth_engine is None:
            return []

        milestones = await self._growth_engine.get_milestones(milestone_type, limit)
        return [asdict(m) for m in milestones]

    async def record_persona_milestone(self, key: str, description: str) -> None:
        """Record a persona-layer milestone, skipping if already recorded."""
        if not self.enable_evolution or self._growth_engine is None:
            return
        existing = await self._growth_engine.get_milestones(MilestoneType.SPECIAL, limit=500)
        if any(m.title == key for m in existing):
            return
        await self._growth_engine.record_milestone(
            milestone_type=MilestoneType.SPECIAL,
            title=key,
            description=f"Persona milestone: {description}",
        )
        logger.info("Persona milestone recorded: %s", key)

    async def process_turn_outcome(
        self,
        user_id: str,
        user_message: str,
        analysis: InteractionAnalysis,
        stp_rules: list | None = None,
        milestone_conditions: dict[str, str] | None = None,
        allow_state_transition: bool = True,
    ) -> bool:
        """Consolidate all per-turn personality updates behind the facade.

        Performs: record_interaction, update_after_interaction,
        record_task_outcome, optional update_stp_trigger, and milestone recording.
        Returns True if any update succeeded.
        """
        updated = False
        try:
            await self.record_interaction(
                user_id=user_id,
                interaction_type=InteractionType.CHAT,
                outcome=analysis.outcome_str,
                sentiment=analysis.sentiment,
                notes=f"Message: {user_message[:100]}...",
            )
            await self.update_after_interaction(
                outcome=analysis.outcome,
                user_engagement=analysis.engagement,
                complexity=analysis.complexity,
            )
            await self.record_task_outcome(
                task_id=f"chat_{int(time.time())}_{user_id}",
                task_category="chat",
                user_satisfaction=analysis.satisfaction,
                accepted=analysis.outcome != InteractionOutcome.FAILURE,
                task_complexity=analysis.complexity,
                task_duration=0.0,
            )
            updated = True
        except Exception as exc:
            logger.warning("Failed to update self memory: %s", exc)

        if allow_state_transition:
            try:
                trigger = analysis.trigger_type or ""
                state_name = ""
                if trigger and stp_rules:
                    config = await self.get_core_personality()
                    for item in getattr(config, "state_transition_protocol", []):
                        if getattr(item, "trigger_type", "") == trigger:
                            state_name = getattr(item, "target_state_name", "")
                            break
                logger.info(
                    "STP trigger update user_id=%s trigger_type=%s state_name=%s",
                    user_id,
                    trigger or None,
                    state_name or None,
                )
                await self.update_stp_trigger(trigger, state_name)
            except Exception as exc:
                logger.warning("Failed to update STP trigger: %s", exc)
        else:
            logger.info("STP trigger update skipped user_id=%s reason=non_chat_scope", user_id)

        # Record detected persona-layer milestones.
        if analysis.milestone_keys:
            try:
                for key in analysis.milestone_keys:
                    desc = (milestone_conditions or {}).get(key, key)
                    await self.record_persona_milestone(key, desc)
            except Exception as exc:
                logger.warning("Failed to record persona milestones: %s", exc)

        return updated
