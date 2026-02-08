"""
复杂度评估器 - 评估任务复杂度
"""
from typing import Dict, Any, List
from .base import TaskComplexity, ComplexityLevel


class ComplexityEvaluator:
    """
    复杂度评估器

    评估任务复杂度，决定是否请求人类帮助
    """

    def __init__(self):
        """初始化复杂度评估器"""
        # 复杂度阈值配置
        self.thresholds = {
            ComplexityLevel.LOW: 30,
            ComplexityLevel.MEDIUM: 50,
            ComplexityLevel.HIGH: 70,
            ComplexityLevel.CRITICAL: 85,
        }

    def evaluate(self, task: Dict[str, Any]) -> TaskComplexity:
        """
        评估任务复杂度

        Args:
            task: 任务描述

        Returns:
            TaskComplexity: 复杂度评估结果
        """
        # 1. 统计工具数量
        tool_count = self._count_tools(task)

        # 2. 估算步骤数量
        step_count = self._estimate_steps(task)

        # 3. 评估参数不确定性
        param_uncertainty = self._assess_parameter_uncertainty(task)

        # 4. 统计依赖关系
        dependency_count = self._count_dependencies(task)

        # 5. 计算复杂度分数 (0-100)
        score = self._calculate_score(
            tool_count,
            step_count,
            param_uncertainty,
            dependency_count
        )

        # 6. 确定复杂度级别
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
        """统计工具数量"""
        # 从任务描述中提取所需工具
        tools = task.get("tools", [])
        if isinstance(tools, list):
            return len(tools)
        return 1  # 默认至少需要1个工具

    def _estimate_steps(self, task: Dict[str, Any]) -> int:
        """估算步骤数量"""
        # 简化版：基于工具数量估算
        # 每个工具平均需要2-3个步骤
        tool_count = self._count_tools(task)
        return tool_count * 2

    def _assess_parameter_uncertainty(self, task: Dict[str, Any]) -> float:
        """评估参数不确定性"""
        params = task.get("parameters", {})

        if not params:
            return 0.0  # 无参数，不确定性低

        # 统计缺失参数
        missing = 0
        total = 0

        for value in params.values():
            total += 1
            if value is None or value == "":
                missing += 1

        return missing / total if total > 0 else 0.0

    def _count_dependencies(self, task: Dict[str, Any]) -> int:
        """统计依赖关系"""
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
        计算复杂度分数

        权重分配：
        - 工具数量: 30%
        - 步骤数量: 30%
        - 参数不确定性: 25%
        - 依赖关系: 15%
        """
        # 工具数量得分 (0-30)
        tool_score = min(tool_count * 5, 30)

        # 步骤数量得分 (0-30)
        step_score = min(step_count * 2, 30)

        # 参数不确定性得分 (0-25)
        uncertainty_score = param_uncertainty * 25

        # 依赖关系得分 (0-15)
        dep_score = min(dependency_count * 3, 15)

        total_score = tool_score + step_score + uncertainty_score + dep_score
        return min(total_score, 100)

    def _determine_level(self, score: float) -> ComplexityLevel:
        """根据分数确定复杂度级别"""
        if score < self.thresholds[ComplexityLevel.LOW]:
            return ComplexityLevel.LOW
        elif score < self.thresholds[ComplexityLevel.MEDIUM]:
            return ComplexityLevel.MEDIUM
        elif score < self.thresholds[ComplexityLevel.HIGH]:
            return ComplexityLevel.HIGH
        else:
            return ComplexityLevel.CRITICAL
