"""
渐进式学习策略
"""
from typing import Dict, Any
from .base import LearningStage, ComplexityLevel


class ProgressiveLearning:
    """
    渐进式学习

    通过渐进式学习提升自主处理能力
    """

    def __init__(self):
        """初始化渐进式学习"""
        self.interaction_count = 0

        # 阶段阈值
        self.stage_thresholds = {
            LearningStage.INITIAL: 0,
            LearningStage.GROWTH: 100,
            LearningStage.MATURE: 1000,
        }

        # 各阶段的复杂度容忍度
        self.stage_tolerance = {
            LearningStage.INITIAL: [ComplexityLevel.LOW],
            LearningStage.GROWTH: [
                ComplexityLevel.LOW,
                ComplexityLevel.MEDIUM
            ],
            LearningStage.MATURE: [
                ComplexityLevel.LOW,
                ComplexityLevel.MEDIUM,
                ComplexityLevel.HIGH
            ],
        }

    @property
    def current_stage(self) -> LearningStage:
        """获取当前学习阶段"""
        if self.interaction_count < self.stage_thresholds[LearningStage.GROWTH]:
            return LearningStage.INITIAL
        elif self.interaction_count < self.stage_thresholds[LearningStage.MATURE]:
            return LearningStage.GROWTH
        else:
            return LearningStage.MATURE

    def record_interaction(self):
        """记录一次交互"""
        self.interaction_count += 1

    async def should_handle_autonomously(
        self,
        complexity: ComplexityLevel
    ) -> bool:
        """
        判断是否应该自主处理

        Args:
            complexity: 任务复杂度

        Returns:
            是否自主处理
        """
        stage = self.current_stage
        tolerance = self.stage_tolerance.get(stage, [])

        return complexity in tolerance

    async def should_request_help(
        self,
        complexity: ComplexityLevel
    ) -> bool:
        """
        判断是否应该请求人类帮助

        Args:
            complexity: 任务复杂度

        Returns:
            是否需要帮助
        """
        return not await self.should_handle_autonomously(complexity)

    def get_stage_info(self) -> Dict[str, Any]:
        """获取阶段信息"""
        stage = self.current_stage
        return {
            "stage": stage.value,
            "interaction_count": self.interaction_count,
            "next_stage_threshold": self._get_next_threshold(),
        }

    def _get_next_threshold(self) -> int:
        """获取下一阶段的阈值"""
        stage = self.current_stage

        if stage == LearningStage.INITIAL:
            return self.stage_thresholds[LearningStage.GROWTH]
        elif stage == LearningStage.GROWTH:
            return self.stage_thresholds[LearningStage.MATURE]
        else:
            return -1  # 已达到最高阶段
