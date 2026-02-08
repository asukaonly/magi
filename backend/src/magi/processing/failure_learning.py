"""
失败学习机制
"""
import hashlib
from typing import Dict, Any, List, Optional
from collections import defaultdict
from .base import FailureCase, FailurePattern


class FailureLearner:
    """
    失败学习器

    从失败经验中学习，避免重复错误
    """

    def __init__(self, llm_adapter=None):
        """
        初始化失败学习器

        Args:
            llm_adapter: LLM适配器（用于智能分析）
        """
        self.llm_adapter = llm_adapter

        # 失败案例存储（按类型分组）
        self._failures_by_type: Dict[str, List[FailureCase]] = defaultdict(list)

        # 失败模式缓存
        self._patterns: Dict[str, FailurePattern] = {}

        # 模式识别阈值
        self.pattern_recognition_threshold = 5  # 5个同类失败触发模式识别

    async def record_failure(
        self,
        task: Dict[str, Any],
        error: Exception,
        execution_steps: List[Dict]
    ):
        """
        记录失败案例

        Args:
            task: 任务描述
            error: 错误
            execution_steps: 执行步骤
        """
        # 生成失败类型
        failure_type = self._classify_failure(task, error)

        # 创建失败案例
        case = FailureCase(
            task_description=task.get("description", ""),
            failure_reason=str(error),
            error_stack=error.__class__.__name__,
            execution_steps=execution_steps,
        )

        # 存储失败案例
        self._failures_by_type[failure_type].append(case)

        # 检查是否需要识别模式
        if await self._should_recognize_pattern(failure_type):
            await self._recognize_pattern(failure_type)

    async def should_request_help(self, task: Dict[str, Any]) -> bool:
        """
        判断是否应该请求人类帮助

        Args:
            task: 任务描述

        Returns:
            是否需要帮助
        """
        failure_type = self._classify_failure_type(task)

        # 如果该类型有失败模式，检查是否匹配
        if failure_type in self._patterns:
            pattern = self._patterns[failure_type]
            # TODO: 更精细的匹配逻辑
            return True

        # 检查历史失败次数
        failures = self._failures_by_type.get(failure_type, [])
        return len(failures) >= 3  # 同类失败3次以上请求帮助

    async def get_avoidance_strategy(
        self,
        task: Dict[str, Any]
    ) -> Optional[str]:
        """
        获取避免策略

        Args:
            task: 任务描述

        Returns:
            避免策略或None
        """
        failure_type = self._classify_failure_type(task)

        if failure_type in self._patterns:
            pattern = self._patterns[failure_type]
            return pattern.avoidance_strategy

        return None

    def _classify_failure(self, task: Dict, error: Exception) -> str:
        """
        分类失败类型

        Args:
            task: 任务
            error: 错误

        Returns:
            失败类型
        """
        # 基于错误类型分类
        error_type = error.__class__.__name__

        # 可以进一步结合任务信息分类
        task_type = task.get("type", "")

        return f"{task_type}:{error_type}"

    def _classify_failure_type(self, task: Dict) -> str:
        """
        预测任务可能的失败类型

        Args:
            task: 任务描述

        Returns:
            失败类型
        """
        # 简化版：基于任务类型
        task_type = task.get("type", "")
        return f"{task_type}:Unknown"

    async def _should_recognize_pattern(self, failure_type: str) -> bool:
        """判断是否应该识别失败模式"""
        failures = self._failures_by_type.get(failure_type, [])
        return len(failures) >= self.pattern_recognition_threshold

    async def _recognize_pattern(self, failure_type: str):
        """
        识别失败模式

        Args:
            failure_type: 失败类型
        """
        failures = self._failures_by_type.get(failure_type, [])

        if not failures:
            return

        # 简化版：基于失败原因生成模式
        # 实际实现可以使用LLM进行智能分析

        # 统计最常见的失败原因
        reason_count = defaultdict(int)
        for case in failures:
            reason_count[case.failure_reason] += 1

        most_common_reason = max(reason_count.items(), key=lambda x: x[1])[0]

        # 生成模式ID
        pattern_id = hashlib.md5(failure_type.encode()).hexdigest()[:8]

        # 创建失败模式
        pattern = FailurePattern(
            pattern_id=pattern_id,
            description=f"失败模式：{failure_type}",
            avoidance_strategy=f"避免：{most_common_reason}",
            case_count=len(failures),
        )

        self._patterns[failure_type] = pattern
