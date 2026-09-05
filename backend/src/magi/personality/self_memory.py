"""SelfMemory facade for persona-scoped emotion, relationships, and milestones."""
import logging
from typing import Dict, Optional, List
from dataclasses import asdict

from .models import (
    EmotionalState,
)
from .loader import PersonalityConfig
from .historical_behavior import clear_historical_behavior_data
from .emotional_state import EmotionalStateEngine, InteractionOutcome, EngagementLevel
from .growth_memory import GrowthMemoryEngine, InteractionType, MilestoneType
from .interaction_analyzer import InteractionAnalysis
from ..utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)


# ===== Unified Management Class =====

class SelfMemory:
    """Persona-scoped emotional state, relationships, and growth milestones."""

    def __init__(
        self,
        personality_name: str,
        db_path: str = None,
        enable_evolution: bool = True,
        *,
        persona_id: str = "",
        personality_config: Optional[PersonalityConfig] = None,
    ):
        runtime_paths = get_runtime_paths()

        self.personality_name = personality_name
        self.persona_id = persona_id
        self.db_path = db_path or str(runtime_paths.self_memory_db_path)
        self.enable_evolution = enable_evolution

        self._historical_behavior_db_path = str(runtime_paths.behavior_db_path)
        self._emotion_engine: Optional[EmotionalStateEngine] = None
        self._growth_engine: Optional[GrowthMemoryEngine] = None

        # cache - store parsed personality config
        self._personality_config: Optional[PersonalityConfig] = personality_config

    async def init(self):
        """initializeallcomponent"""
        # loadPersonality configuration
        await self._load_personality()

        if self.enable_evolution:
            runtime_paths = get_runtime_paths()
            emotion_db = str(runtime_paths.emotional_db_path)
            growth_db = str(runtime_paths.growth_db_path)

            self._emotion_engine = EmotionalStateEngine(emotion_db, persona_id=self.persona_id)
            self._growth_engine = GrowthMemoryEngine(growth_db, persona_id=self.persona_id)

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

        raise RuntimeError(
            f"Personality '{self.personality_name}' not found in registry. "
            "Ensure the persona was seeded and the registry is reachable."
        )

    async def reload_personality(
        self,
        new_personality_name: str = None,
        personality_config: Optional[PersonalityConfig] = None,
    ):
        """Switch the active persona name and optionally swap in a preloaded config."""
        old_personality_name = self.personality_name
        old_personality_config = self._personality_config

        try:
            if new_personality_name:
                self.personality_name = new_personality_name

            # Use the explicitly passed config, or clear so _load_personality
            # re-resolves from cache / registry.
            self._personality_config = personality_config

            await self._load_personality()
        except Exception:
            self.personality_name = old_personality_name
            self._personality_config = old_personality_config
            raise

        if self.enable_evolution and self._growth_engine and self._personality_config:
            from .growth_memory import MilestoneType
            try:
                await self._growth_engine.record_milestone(
                    milestone_type=MilestoneType.FIRST_USE,
                    title=f"Personality switched to {self._personality_config.name}",
                    description=f"Reloaded personality configuration: {self.personality_name}"
                )
            except Exception as exc:
                logger.warning("Failed to record personality switch milestone: %s", exc)

        name = self._personality_config.name if self._personality_config else "Unknown"
        logger.info(f"Personality reloaded: {old_personality_name} -> {self.personality_name} ({name})")


    async def get_core_personality(self) -> PersonalityConfig:
        """getcorePersonality configuration"""
        return self._personality_config or PersonalityConfig()

    async def clear_learned_state(self) -> int:
        """Clear historical behavior, emotion, and growth while preserving persona config."""
        if not self.enable_evolution:
            return 0

        deleted = await clear_historical_behavior_data(self._historical_behavior_db_path)
        for engine in (
            self._emotion_engine,
            self._growth_engine,
        ):
            if engine is not None:
                deleted += int(await engine.clear_all())
        return deleted


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

    async def record_observer_relationship_signal(
        self,
        *,
        user_id: str,
        persona_id: str = "",
        signal_type: str,
        milestone_key: str = "",
        trust_delta: float = 0.0,
        evidence_text: str = "",
        confidence: float = 0.0,
        turn_id: str = "",
        session_id: str = "",
    ) -> bool:
        """Apply a validated persona-scoped relationship signal."""
        _ = persona_id, turn_id, session_id
        if not self.enable_evolution or self._growth_engine is None:
            return False
        if confidence < 0.65:
            return False

        updated = False
        signal = str(signal_type or "").strip().casefold()
        if signal == "trust_delta" and trust_delta:
            updater = getattr(self._growth_engine, "update_relationship_trust", None)
            if updater is not None:
                await updater(user_id, float(trust_delta))
                updated = True

        if signal == "milestone" and milestone_key:
            conditions = getattr(self._personality_config, "milestone_conditions", {}) or {}
            if milestone_key in conditions:
                description = str(conditions.get(milestone_key) or evidence_text or milestone_key)
                await self.record_persona_milestone(milestone_key, description)
                updated = True

        return updated

    async def process_turn_outcome(
        self,
        user_id: str,
        user_message: str,
        analysis: InteractionAnalysis,
        milestone_conditions: dict[str, str] | None = None,
    ) -> bool:
        """Consolidate all per-turn personality updates behind the facade.

        Records relationship, emotional-state, and milestone updates.
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
            updated = True
        except Exception as exc:
            logger.warning("Failed to update self memory: %s", exc)

        # Record detected persona-layer milestones.
        if analysis.milestone_keys:
            try:
                for key in analysis.milestone_keys:
                    desc = (milestone_conditions or {}).get(key, key)
                    await self.record_persona_milestone(key, desc)
            except Exception as exc:
                logger.warning("Failed to record persona milestones: %s", exc)

        return updated
