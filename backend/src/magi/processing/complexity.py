"""
Complexity evaluator - evaluates task complexity
"""
from typing import Dict, Any, List
from .base import TaskComplexity, ComplexityLevel


class ComplexityEvaluator:
    """
    Complexity Evaluator

    Evaluates task complexity to determine whether to request human help.
    """

    def __init__(self):
        """Initialize the Complexity Evaluator."""
        # Complexity threshold configuration
        self.thresholds = {
            ComplexityLevel.LOW: 30,
            ComplexityLevel.MEDIUM: 50,
            ComplexityLevel.HIGH: 70,
            ComplexityLevel.CRITICAL: 85,
        }

    def evaluate(self, task: Dict[str, Any]) -> TaskComplexity:
        """
        Evaluate task complexity.

        Args:
            task: Task description

        Returns:
            TaskComplexity: Complexity evaluation result
        """
        # 1. Count tools
        tool_count = self._count_tools(task)

        # 2. Estimate step count
        step_count = self._estimate_steps(task)

        # 3. Assess parameter uncertainty
        param_uncertainty = self._assess_parameter_uncertainty(task)

        # 4. Count dependencies
        dependency_count = self._count_dependencies(task)

        # 5. Calculate complexity score (0-100)
        score = self._calculate_score(
            tool_count,
            step_count,
            param_uncertainty,
            dependency_count
        )

        # 6. Determine complexity level
        level = self._determine_level(score)

        return TaskComplexity(
            level=level,
            score=score,
            tool_count=tool_count,
            step_count=step_count,
            parameter_uncertainty=param_uncertainty,
            dependency_count=dependency_count,
        )

    def _count_tools(self, task: Dict[str, Any]) -> int:
        """Count the number of tools."""
        # Extract required tools from task description
        tools = task.get("tools", [])
        if isinstance(tools, list):
            return len(tools)
        return 1  # Default: at least 1 tool needed

    def _estimate_steps(self, task: Dict[str, Any]) -> int:
        """Estimate the number of steps."""
        # Simplified: estimate based on tool count
        # Each tool requires 2-3 steps on average
        tool_count = self._count_tools(task)
        return tool_count * 2

    def _assess_parameter_uncertainty(self, task: Dict[str, Any]) -> float:
        """Assess parameter uncertainty."""
        params = task.get("parameters", {})

        if not params:
            return 0.0  # No parameters, low uncertainty

        # Count missing parameters
        missing = 0
        total = 0

        for value in params.values():
            total += 1
            if value is None or value == "":
                missing += 1

        return missing / total if total > 0 else 0.0

    def _count_dependencies(self, task: Dict[str, Any]) -> int:
        """Count dependencies."""
        deps = task.get("dependencies", [])
        return len(deps) if isinstance(deps, list) else 0

    def _calculate_score(
        self,
        tool_count: int,
        step_count: int,
        param_uncertainty: float,
        dependency_count: int
    ) -> float:
        """
        Calculate the complexity score.

        Weight distribution:
        - Tool count: 30%
        - Step count: 30%
        - Parameter uncertainty: 25%
        - Dependencies: 15%
        """
        # Tool count score (0-30)
        tool_score = min(tool_count * 5, 30)

        # Step count score (0-30)
        step_score = min(step_count * 2, 30)

        # Parameter uncertainty score (0-25)
        uncertainty_score = param_uncertainty * 25

        # Dependency score (0-15)
        dep_score = min(dependency_count * 3, 15)

        total_score = tool_score + step_score + uncertainty_score + dep_score
        return min(total_score, 100)

    def _determine_level(self, score: float) -> ComplexityLevel:
        """Determine complexity level based on score."""
        if score < self.thresholds[ComplexityLevel.LOW]:
            return ComplexityLevel.LOW
        elif score < self.thresholds[ComplexityLevel.MEDIUM]:
            return ComplexityLevel.MEDIUM
        elif score < self.thresholds[ComplexityLevel.HIGH]:
            return ComplexityLevel.HIGH
        else:
            return ComplexityLevel.CRITICAL
