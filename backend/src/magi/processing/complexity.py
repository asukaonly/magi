"""
complex度评估器 - 评估任务complex度
"""
from typing import Dict, Any, List
from .base import TaskComplexity, Complexitylevel


class ComplexityEvaluator:
    """
    complex度评估器

    评估任务complex度，决定is notrequest人Class帮助
    """

    def __init__(self):
        """initializecomplex度评估器"""
        # complex度阈ValueConfiguration
        self.thresholds = {
            Complexitylevel.LOW: 30,
            Complexitylevel.MEDIUM: 50,
            Complexitylevel.HIGH: 70,
            Complexitylevel.CRITICAL: 85,
        }

    def evaluate(self, task: Dict[str, Any]) -> TaskComplexity:
        """
        评估任务complex度

        Args:
            task: 任务Description

        Returns:
            TaskComplexity: complex度评估Result
        """
        # 1. statisticstoolquantity
        tool_count = self._count_tools(task)

        # 2. 估算stepquantity
        step_count = self._estimate_steps(task)

        # 3. 评估Parameter不确定性
        param_uncertainty = self._assess_parameter_uncertainty(task)

        # 4. statisticsdependencyrelationship
        dependency_count = self._count_dependencies(task)

        # 5. calculatecomplex度score (0-100)
        score = self._calculate_score(
            tool_count,
            step_count,
            param_uncertainty,
            dependency_count
        )

        # 6. 确定complex度level
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
        """statisticstoolquantity"""
        # 从任务Description中提取所需tool
        tools = task.get("tools", [])
        if isinstance(tools, list):
            return len(tools)
        return 1  # default至少需要1个tool

    def _estimate_steps(self, task: Dict[str, Any]) -> int:
        """估算stepquantity"""
        # 简化版：基于toolquantity估算
        # 每个tool平均需要2-3个step
        tool_count = self._count_tools(task)
        return tool_count * 2

    def _assess_parameter_uncertainty(self, task: Dict[str, Any]) -> float:
        """评估Parameter不确定性"""
        params = task.get("parameters", {})

        if not params:
            return 0.0  # 无Parameter，不确定性低

        # statistics缺失Parameter
        missing = 0
        total = 0

        for value in params.values():
            total += 1
            if value is None or value == "":
                missing += 1

        return missing / total if total > 0 else 0.0

    def _count_dependencies(self, task: Dict[str, Any]) -> int:
        """statisticsdependencyrelationship"""
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
        calculatecomplex度score

        weight分配：
        - toolquantity: 30%
        - stepquantity: 30%
        - Parameter不确定性: 25%
        - dependencyrelationship: 15%
        """
        # toolquantity得分 (0-30)
        tool_score = min(tool_count * 5, 30)

        # stepquantity得分 (0-30)
        step_score = min(step_count * 2, 30)

        # Parameter不确定性得分 (0-25)
        uncertainty_score = param_uncertainty * 25

        # dependencyrelationship得分 (0-15)
        dep_score = min(dependency_count * 3, 15)

        total_score = tool_score + step_score + uncertainty_score + dep_score
        return min(total_score, 100)

    def _determine_level(self, score: float) -> Complexitylevel:
        """根据score确定complex度level"""
        if score < self.thresholds[Complexitylevel.LOW]:
            return Complexitylevel.LOW
        elif score < self.thresholds[Complexitylevel.MEDIUM]:
            return Complexitylevel.MEDIUM
        elif score < self.thresholds[Complexitylevel.HIGH]:
            return Complexitylevel.HIGH
        else:
            return Complexitylevel.CRITICAL
