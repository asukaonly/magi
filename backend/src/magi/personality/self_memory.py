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
from typing import Dict, Any, Optional, List
from dataclasses import asdict

from .models import (
    EmotionalState,
)
from .loader import PersonalityLoader, PersonalityConfig
from .behavior_evolution import BehaviorEvolutionEngine, SatisfactionLevel
from .emotional_state import EmotionalStateEngine, InteractionOutcome, EngagementLevel
from .growth_memory import GrowthMemoryEngine, InteractionType, MilestoneType
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
        personalities_path: str = None,
        db_path: str = None,
        enable_evolution: bool = True
    ):
        """
        Internal note.

        Args:
            personality_name: Personality name
            Internal note.
            Internal note.
            enable_evolution: is notEnablepersonalityevolution
        """
        # Internal note.
        runtime_paths = get_runtime_paths()

        self.personality_name = personality_name
        self.personalities_path = personalities_path or str(runtime_paths.personalities_dir)
        self.db_path = db_path or str(runtime_paths.self_memory_db_path)
        self.enable_evolution = enable_evolution

        # Internal note.
        self._personality_loader: Optional[PersonalityLoader] = None
        self._behavior_engine: Optional[BehaviorEvolutionEngine] = None
        self._emotion_engine: Optional[EmotionalStateEngine] = None
        self._growth_engine: Optional[GrowthMemoryEngine] = None

        # cache - store parsed personality config
        self._personality_config: Optional[PersonalityConfig] = None

    async def init(self):
        """initializeallcomponent"""
        # initializePersonality Loader
        self._personality_loader = PersonalityLoader(self.personalities_path)

        # loadPersonality configuration
        await self._load_personality()

        if self.enable_evolution:
            # Internal note.
            runtime_paths = get_runtime_paths()
            behavior_db = str(runtime_paths.behavior_db_path)
            emotion_db = str(runtime_paths.emotional_db_path)
            growth_db = str(runtime_paths.growth_db_path)

            self._behavior_engine = BehaviorEvolutionEngine(behavior_db)
            self._emotion_engine = EmotionalStateEngine(emotion_db)
            self._growth_engine = GrowthMemoryEngine(growth_db)

            await self._behavior_engine.init()
            await self._emotion_engine.init()
            await self._growth_engine.init()

            # recordinitializemilestone
            await self._growth_engine.record_milestone(
                milestone_type=MilestoneType.FIRST_USE,
                title=f"initialized as {self._personality_config.name}",
                description=f"Personality {self.personality_name} loaded and initialized"
            )

        logger.info(f"SelfMemory initialized with personality: {self.personality_name}")

    async def _load_personality(self):
        """Load personality configuration from JSON."""
        try:
            config = self._personality_loader.load(self.personality_name)
            self._personality_config = config
            logger.info(f"Loaded personality: {config.name}")
        except FileNotFoundError:
            logger.warning(f"Personality {self.personality_name} not found, using default")
            self._personality_config = PersonalityConfig()

    async def reload_personality(self, new_personality_name: str = None):
        """
        Internal note.

        Args:
            Internal note.
        """
        old_personality_name = self.personality_name

        if new_personality_name:
            self.personality_name = new_personality_name

        # Internal note.
        if self._personality_loader:
            self._personality_loader.clear_cache(old_personality_name)
            if new_personality_name and new_personality_name != old_personality_name:
                self._personality_loader.clear_cache(new_personality_name)

        # Internal note.
        self._personality_config = None

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

        name = self._personality_config.name if self._personality_config else "Unknotttwn"
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

    async def store_experience(self, perception, action, result):
        """
        Internal note.

        Args:
            perception: Perception
            action: Action
            result: Result
        """
        # Experience storage is primarily handled by the current memory system.
        # This hook remains only for legacy callers that still forward experience tuples.
        logger = logging.getLogger(__name__)

        # Extract interaction information if available
        user_id = None
        if hasattr(perception, 'data') and isinstance(perception.data, dict):
            user_id = perception.data.get('user_id') or perception.data.get('message', {}).get('user_id')

        # Record interaction if evolution is enabled and user_id is available
        if user_id and self.enable_evolution:
            from .growth_memory import InteractionType

            # Determine outcome based on result
            outcome = "positive"
            if hasattr(result, 'success'):
                outcome = "positive" if result.success else "negative"

            # Record the interaction
            await self.record_interaction(
                user_id=user_id,
                interaction_type=InteractionType.CHAT,
                outcome=outcome,
                notes=f"Action: {type(action).__name__ if action else 'None'}"
            )
            logger.debug(f"Experience stored for user {user_id}")

    # Internal note.

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

    async def get_milestones(self, milestone_type: str | None = None, limit: int = 100) -> List[Dict]:
        """Deprecated: kept for compatibility, forwards to growth engine if available."""
        if not self.enable_evolution or self._growth_engine is None:
            return []

        milestones = await self._growth_engine.get_milestones(milestone_type, limit)
        return [asdict(m) for m in milestones]
