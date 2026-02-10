"""
自我记忆系统 v2 - AI人格核心

参考RPG角色卡设计，赋予AI灵魂和一致性

层级结构：
1. 核心人格层 (Core Personality) - 全场景通用，从Markdown加载
2. 认知能力层 (Cognition & Capability) - 按场景加载，从Markdown加载
3. 行为偏好层 (Behavioral Preference) - 按任务演化
4. 情绪状态层 (Emotional State) - 动态变化
5. 成长记忆层 (Growth Memory) - 长期演化
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
from .personality_loader import PersonalityLoader
from .behavior_evolution import BehaviorEvolutionEngine, SatisfactionLevel
from .emotional_state import EmotionalStateEngine, InteractionOutcome, EngagementLevel
from .growth_memory import GrowthMemoryEngine, MilestoneType, InteractionType
from .context_builder import ContextBuilder, Scenario
from ..utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)


# ===== 统一管理类 =====

class SelfMemoryV2:
    """
    自我记忆系统 v2

    管理所有层级的人格和记忆数据
    """

    def __init__(
        self,
        personality_name: str = "default",
        personalities_path: str = None,
        db_path: str = None,
        enable_evolution: bool = True
    ):
        """
        初始化自我记忆系统

        Args:
            personality_name: 人格名称
            personalities_path: 人格配置文件目录（默认使用运行时目录）
            db_path: 数据库路径（默认使用运行时目录）
            enable_evolution: 是否启用人格演化
        """
        # 使用运行时路径作为默认值
        runtime_paths = get_runtime_paths()

        self.personality_name = personality_name
        self.personalities_path = personalities_path or str(runtime_paths.personalities_dir)
        self.db_path = db_path or str(runtime_paths.self_memory_db_path)
        self.enable_evolution = enable_evolution

        # 子组件
        self._personality_loader: Optional[PersonalityLoader] = None
        self._behavior_engine: Optional[BehaviorEvolutionEngine] = None
        self._emotion_engine: Optional[EmotionalStateEngine] = None
        self._growth_engine: Optional[GrowthMemoryEngine] = None
        self._context_builder: ContextBuilder = ContextBuilder()

        # 缓存
        self._core_personality: Optional[CorePersonality] = None
        self._cognition_profiles: Dict[str, CognitionProfile] = {}

    async def init(self):
        """初始化所有组件"""
        # 初始化人格加载器
        self._personality_loader = PersonalityLoader(self.personalities_path)

        # 加载人格配置
        await self._load_personality()

        if self.enable_evolution:
            # 使用运行时路径
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

            # 记录初始化里程碑
            await self._growth_engine.record_milestone(
                milestone_type=MilestoneType.FIRST_USE,
                title=f"Initialized as {self._core_personality.name}",
                description=f"Personality {self.personality_name} loaded and initialized"
            )

        logger.info(f"SelfMemoryV2 initialized with personality: {self.personality_name}")

    async def _load_personality(self):
        """从Markdown加载人格配置"""
        try:
            config = self._personality_loader.load(self.personality_name)
            self._core_personality = self._personality_loader.to_core_personality(config)
            self._cognition_profiles["default"] = self._personality_loader.to_cognition_profile(config)
            logger.info(f"Loaded personality: {self._core_personality.name}")
        except FileNotFoundError:
            logger.warning(f"Personality {self.personality_name} not found, using default")
            self._core_personality = CorePersonality(
                name="AI Assistant",
                role="Helper"
            )
            self._cognition_profiles["default"] = CognitionProfile()

    # ===== 核心人格层 =====

    async def get_core_personality(self) -> CorePersonality:
        """获取核心人格"""
        return self._core_personality

    # ===== 认知能力层 =====

    async def get_cognition_profile(self, scenario: str = "default") -> CognitionProfile:
        """获取场景的认知配置"""
        if scenario not in self._cognition_profiles:
            # 使用默认配置
            return self._cognition_profiles.get("default", CognitionProfile())
        return self._cognition_profiles[scenario]

    # ===== 行为偏好层 =====

    async def get_behavior_profile(self, task_category: str) -> TaskBehaviorProfile:
        """获取任务类别的行为配置"""
        if not self.enable_evolution or self._behavior_engine is None:
            return TaskBehaviorProfile(task_category=task_category)

        return await self._behavior_engine.get_behavior_profile(task_category)

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
        """记录任务交互结果"""
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

    # ===== 情绪状态层 =====

    async def get_emotional_state(self) -> EmotionalState:
        """获取当前情绪状态"""
        if not self.enable_evolution or self._emotion_engine is None:
            return EmotionalState()

        return await self._emotion_engine.get_current_state()

    async def update_after_interaction(
        self,
        outcome: InteractionOutcome,
        user_engagement: EngagementLevel = EngagementLevel.MEDIUM,
        complexity: float = 0.5,
    ):
        """交互后更新情绪状态"""
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
        """任务完成后更新情绪状态"""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.update_after_task_completion(
                success=success,
                complexity=complexity,
                duration=duration,
            )

    async def decay_over_time(self, elapsed_minutes: float):
        """时间流逝后的状态衰减"""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.decay_over_time(elapsed_minutes)

    async def recover(self, recovery_type: str = "rest"):
        """恢复机制"""
        if self.enable_evolution and self._emotion_engine:
            await self._emotion_engine.recover(recovery_type)

    # ===== 成长记忆层 =====

    async def record_interaction(
        self,
        user_id: str,
        interaction_type: InteractionType,
        outcome: str = "neutral",
        sentiment: float = 0.0,
        notes: str = ""
    ):
        """记录与用户的交互"""
        if self.enable_evolution and self._growth_engine:
            await self._growth_engine.record_interaction(
                user_id=user_id,
                interaction_type=interaction_type,
                outcome=outcome,
                sentiment=sentiment,
                notes=notes,
            )

    async def get_relationship(self, user_id: str) -> Optional[Dict]:
        """获取与用户的关系"""
        if not self.enable_evolution or self._growth_engine is None:
            return None

        profile = await self._growth_engine.get_relationship(user_id)
        if profile:
            return asdict(profile)
        return None

    async def get_milestones(self, milestone_type: MilestoneType = None, limit: int = 100) -> List[Dict]:
        """获取里程碑"""
        if not self.enable_evolution or self._growth_engine is None:
            return []

        milestones = await self._growth_engine.get_milestones(milestone_type, limit)
        return [asdict(m) for m in milestones]

    async def get_growth_summary(self) -> Dict[str, Any]:
        """获取成长摘要"""
        if not self.enable_evolution or self._growth_engine is None:
            return {}

        return await self._growth_engine.get_growth_summary()

    # ===== 上下文构建 =====

    async def build_context(
        self,
        scenario: str = Scenario.CHAT,
        task_category: str = "general",
        user_id: str = None,
    ) -> str:
        """
        构建人格上下文（用于LLM提示词）

        Args:
            scenario: 交互场景
            task_category: 任务类别
            user_id: 用户ID（可选，用于获取关系信息）

        Returns:
            格式化的人格描述
        """
        # 获取各层数据
        core = await self.get_core_personality()
        cognition = await self.get_cognition_profile(scenario)
        behavior = await self.get_behavior_profile(task_category)
        emotion = await self.get_emotional_state()

        # 获取成长记忆
        growth = None
        if self.enable_evolution and self._growth_engine:
            summary = await self._growth_engine.get_growth_summary()
            milestones = await self._growth_engine.get_milestones(limit=10)
            growth = GrowthMemory(
                milestones=milestones,
                total_interactions=summary.get("total_interactions", 0),
                interaction_days=summary.get("active_days", 0),
            )

        # 获取用户档案
        user_profile = None
        if user_id and self._growth_engine:
            relationship = await self._growth_engine.get_relationship(user_id)
            if relationship:
                user_profile = {
                    "user_id": user_id,
                    "relationship_depth": relationship.depth,
                    "trust_level": relationship.trust_level,
                    "preferences": {},
                }

        # 构建上下文
        return self._context_builder.build_full_context(
            core_personality=core,
            cognition_profile=cognition,
            behavior_profile=behavior,
            emotional_state=emotion,
            growth_memory=growth,
            user_profile=user_profile,
            scenario=scenario,
        )

    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户档案（包含关系信息）"""
        if not user_id or not self.enable_evolution or self._growth_engine is None:
            return None

        relationship = await self._growth_engine.get_relationship(user_id)
        if relationship:
            return asdict(relationship)
        return None

    # ===== 导出和重置 =====

    async def export_personality_card(self) -> Dict[str, Any]:
        """导出完整人格卡"""
        core = await self.get_core_personality()
        emotion = await self.get_emotional_state()
        growth_summary = await self.get_growth_summary()

        return {
            "name": core.name,
            "role": core.role,
            "backstory": core.backstory,
            "personality": {
                "traits": core.traits,
                "virtues": core.virtues,
                "flaws": core.flaws,
                "communication_style": core.communication_distance.value,
                "value_alignment": core.value_alignment.value,
            },
            "level": {
                "total_interactions": growth_summary.get("total_interactions", 0),
                "active_days": growth_summary.get("active_days", 0),
            },
            "current_state": {
                "mood": emotion.current_mood,
                "energy": int(emotion.energy_level * 100),
                "stress": int(emotion.stress_level * 100),
            },
            "milestones": growth_summary.get("milestones", []),
        }

    async def reset_evolution(self, category: str = None):
        """重置演化数据"""
        if not self.enable_evolution:
            return

        if category and self._behavior_engine:
            await self._behavior_engine.reset_category(category)

        if self._emotion_engine:
            await self._emotion_engine.reset()

        if self._growth_engine and category:
            await self._growth_engine.reset_user(category)
