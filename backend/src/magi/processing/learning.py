"""
Progressive learning strategy
"""
from typing import Dict, Any
from .base import LearningStage, ComplexityLevel


class ProgressiveLearning:
    """
    Progressive Learning

    Improves autonomous processing capabilities through progressive learning.
    """

    def __init__(self):
        """Initialize Progressive Learning."""
        self.interaction_count = 0

        # Stage thresholds
        self.stage_thresholds = {
            LearningStage.INITIAL: 0,
            LearningStage.GROWTH: 100,
            LearningStage.MATURE: 1000,
        }

        # Complexity tolerance per stage
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
        """Get current learning stage."""
        if self.interaction_count < self.stage_thresholds[LearningStage.GROWTH]:
            return LearningStage.INITIAL
        elif self.interaction_count < self.stage_thresholds[LearningStage.MATURE]:
            return LearningStage.GROWTH
        else:
            return LearningStage.MATURE

    def record_interaction(self):
        """Record an interaction."""
        self.interaction_count += 1

    async def should_handle_autonotttmously(
        self,
        complexity: ComplexityLevel
    ) -> bool:
        """
        Determine whether to handle a task autonomously.

        Args:
            complexity: Task complexity

        Returns:
            Whether to handle autonomously
        """
        stage = self.current_stage
        tolerance = self.stage_tolerance.get(stage, [])

        return complexity in tolerance

    async def should_request_help(
        self,
        complexity: ComplexityLevel
    ) -> bool:
        """
        Determine whether to request human help.

        Args:
            complexity: Task complexity

        Returns:
            Whether help is needed
        """
        return not await self.should_handle_autonotttmously(complexity)

    def get_stage_info(self) -> Dict[str, Any]:
        """Get stage information."""
        stage = self.current_stage
        return {
            "stage": stage.value,
            "interaction_count": self.interaction_count,
            "next_stage_threshold": self._get_next_threshold(),
        }

    def _get_next_threshold(self) -> int:
        """Get the threshold for the next stage."""
        stage = self.current_stage

        if stage == LearningStage.INITIAL:
            return self.stage_thresholds[LearningStage.GROWTH]
        elif stage == LearningStage.GROWTH:
            return self.stage_thresholds[LearningStage.MATURE]
        else:
            return -1  # Already at the highest stage
