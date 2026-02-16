"""
自我Memory System - AIpersonalitycore

referenceRPGrole卡设计，赋予AI灵魂andconsistency

层级structure：
1. corepersonality层 (Core Personality) - 全scenario通用，从Markdownload
2. 认知capability层 (Cognition & Capability) - 按scenarioload，从Markdownload
3. row为preference层 (Behavioral Preference) - 按任务evolution
4. emotionState层 (Emotional State) - dynamic变化
5. growthmemory层 (Growth Memory) - 长期evolution
"""
import aiosqlite
import json
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import asdict

from .models import (
    CorePersonality,
    CognitionProfile,
    TaskBehaviorProfile,
    EmotionalState,
    GrowthMemory,
    LanguageStyle,
    CommunicationDistance,
    ValueAlignment,
    ThinkingStyle,
    RiskPreference,
    AmbiguityTolerance,
    DomainExpertise,
)
from .personality_loader import PersonalityLoader, PersonalityConfig
from .behavior_evolution import BehaviorEvolutionEngine, Satisfactionlevel
from .emotional_state import EmotionalStateEngine, InteractionOutcome, Engagementlevel
from .growth_memory import GrowthMemoryEngine, Milestonetype, Interactiontype
from .context_builder import ContextBuilder, Scenario
from ..utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)


# ===== Unified Management Class =====

class SelfMemory:
    """
    自我Memory System

    管理all层级的personalityandmemorydata
    """

    def __init__(
        self,
        personality_name: str = "default",
        personalities_path: str = None,
        db_path: str = None,
        enable_evolution: bool = True
    ):
        """
        initialize自我Memory System

        Args:
            personality_name: Personality name
            personalities_path: Personality configurationfiledirectory（default使用run时directory）
            db_path: databasepath（default使用run时directory）
            enable_evolution: is notEnablepersonalityevolution
        """
        # 使用run时path作为defaultValue
        runtime_paths = get_runtime_paths()

        self.personality_name = personality_name
        self.personalities_path = personalities_path or str(runtime_paths.personalities_dir)
        self.db_path = db_path or str(runtime_paths.self_memory_db_path)
        self.enable_evolution = enable_evolution

        # 子component
        self._personality_loader: Optional[PersonalityLoader] = None
        self._behavior_engine: Optional[BehaviorEvolutionEngine] = None
        self._emotion_engine: Optional[EmotionalStateEngine] = None
        self._growth_engine: Optional[GrowthMemoryEngine] = None
        self._context_builder: ContextBuilder = ContextBuilder()

        # cache - 直接storage原始ContentandConfiguration
        self._personality_config: Optional[PersonalityConfig] = None
        self._raw_personality_content: str = ""  # 原始 md Content

    async def init(self):
        """initializeallcomponent"""
        # initializePersonality Loader
        self._personality_loader = PersonalityLoader(self.personalities_path)

        # loadPersonality configuration
        await self._load_personality()

        if self.enable_evolution:
            # 使用run时path
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
                milestone_type=Milestonetype.FIRST_USE,
                title=f"initialized as {self._personality_config.name}",
                description=f"Personality {self.personality_name} loaded and initialized"
            )

        logger.info(f"SelfMemory initialized with personality: {self.personality_name}")

    async def _load_personality(self):
        """从MarkdownloadPersonality configuration"""
        try:
            config = self._personality_loader.load(self.personality_name)
            self._personality_config = config
            # 同时load原始 md Content
            self._raw_personality_content = self._personality_loader.load_raw(self.personality_name)
            logger.info(f"Loaded personality: {config.name}")
        except FileNotFoundError:
            logger.warning(f"Personality {self.personality_name} not found, using default")
            self._personality_config = PersonalityConfig()
            self._raw_personality_content = ""

    async def reload_personality(self, new_personality_name: str = None):
        """
        重newloadPersonality configuration

        Args:
            new_personality_name: newPersonality name（optional，如果不指定则重newloadcurrentpersonality）
        """
        old_personality_name = self.personality_name

        if new_personality_name:
            self.personality_name = new_personality_name

        # 清除Personality Loader的cache
        if self._personality_loader:
            self._personality_loader.clear_cache(old_personality_name)
            if new_personality_name and new_personality_name != old_personality_name:
                self._personality_loader.clear_cache(new_personality_name)

        # 清除已load的personalitydata
        self._personality_config = None
        self._raw_personality_content = ""

        # 重newload
        await self._load_personality()

        # record切换milestone
        if self.enable_evolution and self._growth_engine and self._personality_config:
            from .growth_memory import Milestonetype
            await self._growth_engine.record_milestone(
                milestone_type=Milestonetype.FIRST_USE,
                title=f"Personality switched to {self._personality_config.name}",
                description=f"Reloaded personality configuration: {self.personality_name}"
            )

        name = self._personality_config.name if self._personality_config else "Unknotttwn"
        logger.info(f"Personality reloaded: {old_personality_name} -> {self.personality_name} ({name})")

    # ===== corepersonality层 =====

    async def get_core_personality(self) -> PersonalityConfig:
        """getcorePersonality configuration"""
        return self._personality_config or PersonalityConfig()

    # ===== 认知capability层 =====

    async def get_cognition_profile(self, scenario: str = "default") -> CognitionProfile:
        """getscenario的认知Configuration - deprecated，ReturndefaultValue"""
        return CognitionProfile()

    # ===== row为preference层 =====

    async def get_behavior_profile(self, task_category: str) -> TaskBehaviorProfile:
        """get任务Class别的row为Configuration"""
        if not self.enable_evolution or self._behavior_engine is None:
            return TaskBehaviorProfile(task_category=task_category)

        return await self._behavior_engine.get_behavior_profile(task_category)

    async def record_task_outcome(
        self,
        task_id: str,
        task_category: str,
        user_satisfaction: Satisfactionlevel = Satisfactionlevel.NEUTRAL,
        clarification_count: int = 0,
        confirmation_count: int = 0,
        correction_count: int = 0,
        task_complexity: float = 0.5,
        task_duration: float = 0.0,
        accepted: bool = True,
    ):
        """record任务交互Result"""
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

    # ===== emotionState层 =====

    async def get_emotional_state(self) -> EmotionalState:
        """getcurrentemotionState"""
        if not self.enable_evolution or self._emotion_engine is None:
            return EmotionalState()

        return await self._emotion_engine.get_current_state()

    async def update_after_interaction(
        self,
        outcome: InteractionOutcome,
        user_engagement: Engagementlevel = Engagementlevel.MEDIUM,
        complexity: float = 0.5,
    ):
        """交互后updateemotionState"""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.update_after_interaction(
                outcome=outcome,
                user_engagement=user_engagement,
                complexity=complexity,
            )

    async def update_after_task_completion(
        self,
        success: bool,
        complexity: float,
        duration: float
    ):
        """任务complete后updateemotionState"""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.update_after_task_completion(
                success=success,
                complexity=complexity,
                duration=duration,
            )

    async def decay_over_time(self, elapsed_minutes: float):
        """时间流逝后的State衰减"""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.decay_over_time(elapsed_minutes)

    async def recover(self, recovery_type: str = "rest"):
        """restore机制"""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.recover(recovery_type)

    async def store_experience(self, perception, action, result):
        """
        storageexperience（用于LoopEngine的Reflect阶段）

        Args:
            perception: Perception
            action: Action
            result: Result
        """
        # Experience storage is notttw primarily handled by the L1-L5 memory system
        # This method is a compatibility shim for LoopEngine's reflect phase
        logger = logging.getLogger(__name__)

        # Extract interaction information if available
        user_id = None
        if hasattr(perception, 'data') and isinstance(perception.data, dict):
            user_id = perception.data.get('user_id') or perception.data.get('message', {}).get('user_id')

        # Record interaction if evolution is enabled and user_id is available
        if user_id and self.enable_evolution:
            from .growth_memory import Interactiontype

            # Determine outcome based on result
            outcome = "positive"
            if hasattr(result, 'success'):
                outcome = "positive" if result.success else "negative"

            # Record the interaction
            await self.record_interaction(
                user_id=user_id,
                interaction_type=Interactiontype.CHAT,
                outcome=outcome,
                notes=f"Action: {type(action).__name__ if action else 'None'}"
            )
            logger.debug(f"Experience stored for user {user_id}")

    # ===== growthmemory层 =====

    async def record_interaction(
        self,
        user_id: str,
        interaction_type: Interactiontype,
        outcome: str = "neutral",
        sentiment: float = 0.0,
        notes: str = ""
    ):
        """record与user的交互"""
        if self.enable_evolution and self._growth_engine:
            await self._growth_engine.record_interaction(
                user_id=user_id,
                interaction_type=interaction_type,
                outcome=outcome,
                sentiment=sentiment,
                notes=notes,
            )

    async def get_relationship(self, user_id: str) -> Optional[Dict]:
        """get与user的relationship"""
        if not self.enable_evolution or self._growth_engine is None:
            return None

        profile = await self._growth_engine.get_relationship(user_id)
        if profile:
            return asdict(profile)
        return None

    async def get_milestones(self, milestone_type: Milestonetype = None, limit: int = 100) -> List[Dict]:
        """getmilestone"""
        if not self.enable_evolution or self._growth_engine is None:
            return []

        milestones = await self._growth_engine.get_milestones(milestone_type, limit)
        return [asdict(m) for m in milestones]

    async def get_growth_summary(self) -> Dict[str, Any]:
        """getgrowthsummary"""
        if not self.enable_evolution or self._growth_engine is None:
            return {}

        return await self._growth_engine.get_growth_summary()

    # ===== contextbuild =====

    async def build_context(
        self,
        scenario: str = Scenario.CHAT,
        task_category: str = "general",
        user_id: str = None,
    ) -> str:
        """
        buildpersonalitycontext（用于LLMprompt词）

        直接使用原始 md fileContent，不做额外process

        Args:
            scenario: 交互scenario
            task_category: 任务Class别
            user_id: userid（optional，用于getrelationshipinfo）

        Returns:
            format化的personalityDescription
        """
        parts = []

        # 1. 直接使用原始 md Content作为personality定义
        if self._raw_personality_content:
            parts.append(self._raw_personality_content)

        # 2. getemotionState（仅当非中性时）
        if self.enable_evolution and self._emotion_engine:
            emotion = await self._emotion_engine.get_current_state()
            if emotion.current_mood != "neutral":
                parts.append(f"\n## Current State\n\n- Mood: {emotion.current_mood}\n- Energy: {int(emotion.energy_level*100)}%\n")

        # 3. getuser档案
        if user_id and self._growth_engine:
            relationship = await self._growth_engine.get_relationship(user_id)
            if relationship:
                parts.append(f"\n## About the User\n\n- Relationship depth: {relationship.depth:.1f}\n- Trust level: {relationship.trust_level:.1f}\n")

        return "\n\n".join(parts)

    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """getuser档案（containsrelationshipinfo）"""
        if not user_id or not self.enable_evolution or self._growth_engine is None:
            return None

        relationship = await self._growth_engine.get_relationship(user_id)
        if relationship:
            return asdict(relationship)
        return None

    # ===== exportandreset =====

    async def export_personality_card(self) -> Dict[str, Any]:
        """export完整personality卡"""
        config = await self.get_core_personality()
        emotion = await self.get_emotional_state()
        growth_summary = await self.get_growth_summary()

        return {
            "name": config.name,
            "archetype": config.archetype,
            "backstory": config.backstory,
            "personality": {
                "tone": config.tone,
                "confidence": config.confidence_level,
                "empathy": config.empathy_level,
                "patience": config.patience_level,
            },
            "level": {
                "total_interactions": growth_summary.get("total_interactions", 0),
                "active_days": growth_summary.get("active_days", 0),
            },
            "current_state": {
                "mood": emotion.current_mood if emotion else "neutral",
                "energy": int(emotion.energy_level * 100) if emotion else 100,
                "stress": int(emotion.stress_level * 100) if emotion else 0,
            },
            "milestones": growth_summary.get("milestones", []),
        }

    async def reset_evolution(self, category: str = None):
        """resetevolutiondata"""
        if not self.enable_evolution:
            return

        if category and self._behavior_engine:
            await self._behavior_engine.reset_category(category)

        if self._emotion_engine:
            await self._emotion_engine.reset()

        if self._growth_engine and category:
            await self._growth_engine.reset_user(category)
