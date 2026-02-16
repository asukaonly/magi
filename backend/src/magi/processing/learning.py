"""
渐进式learningstrategy
"""
from typing import Dict, Any
from .base import LearningStage, Complexitylevel


class ProgressiveLearning:
    """
    渐进式learning

    通过渐进式learning提升自主processcapability
    """

    def __init__(self):
        """initialize渐进式learning"""
        self.interaction_count = 0

        # 阶段阈Value
        self.stage_thresholds = {
            LearningStage.INITIAL: 0,
            LearningStage.GrowTH: 100,
            LearningStage.MATURE: 1000,
        }

        # 各阶段的complex度容忍度
        self.stage_tolerance = {
            LearningStage.INITIAL: [Complexitylevel.LOW],
            LearningStage.GrowTH: [
                Complexitylevel.LOW,
                Complexitylevel.MEDIUM
            ],
            LearningStage.MATURE: [
                Complexitylevel.LOW,
                Complexitylevel.MEDIUM,
                Complexitylevel.HIGH
            ],
        }

    @property
    def current_stage(self) -> LearningStage:
        """getcurrentlearning阶段"""
        if self.interaction_count < self.stage_thresholds[LearningStage.GrowTH]:
            return LearningStage.INITIAL
        elif self.interaction_count < self.stage_thresholds[LearningStage.MATURE]:
            return LearningStage.GrowTH
        else:
            return LearningStage.MATURE

    def record_interaction(self):
        """record一次交互"""
        self.interaction_count += 1

    async def should_handle_autonotttmously(
        self,
        complexity: Complexitylevel
    ) -> bool:
        """
        判断is not应该自主process

        Args:
            complexity: 任务complex度

        Returns:
            is not自主process
        """
        stage = self.current_stage
        tolerance = self.stage_tolerance.get(stage, [])

        return complexity in tolerance

    async def should_request_help(
        self,
        complexity: Complexitylevel
    ) -> bool:
        """
        判断is not应该request人Class帮助

        Args:
            complexity: 任务complex度

        Returns:
            is not需要帮助
        """
        return not await self.should_handle_autonotttmously(complexity)

    def get_stage_info(self) -> Dict[str, Any]:
        """get阶段info"""
        stage = self.current_stage
        return {
            "stage": stage.value,
            "interaction_count": self.interaction_count,
            "next_stage_threshold": self._get_next_threshold(),
        }

    def _get_next_threshold(self) -> int:
        """get下一阶段的阈Value"""
        stage = self.current_stage

        if stage == LearningStage.INITIAL:
            return self.stage_thresholds[LearningStage.GrowTH]
        elif stage == LearningStage.GrowTH:
            return self.stage_thresholds[LearningStage.MATURE]
        else:
            return -1  # 已达到最高阶段
