"""
超时计算器
"""
from typing import Dict, Optional
from enum import Enum


class TaskType(Enum):
    """任务类型"""
    SIMPLE = "simple"           # 简单任务
    COMPUTATION = "computation" # 计算任务
    IO = "io"                   # IO任务
    NETWORK = "network"         # 网络任务
    INTERACTIVE = "interactive" # 交互任务
    LONG_RUNNING = "long_running"  # 长期任务


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class TimeoutCalculator:
    """
    超时计算器

    基于任务类型、优先级、交互级别等多维度计算超时时间
    """

    def __init__(self):
        """初始化超时计算器"""

        # 基础超时配置（秒）
        self.base_timeouts = {
            TaskType.SIMPLE: 5.0,
            TaskType.COMPUTATION: 30.0,
            TaskType.IO: 10.0,
            TaskType.NETWORK: 15.0,
            TaskType.INTERACTIVE: 60.0,
            TaskType.LONG_RUNNING: 300.0,
        }

        # 优先级系数（优先级越高，超时越短）
        self.priority_factors = {
            TaskPriority.LOW: 2.0,      # 低优先级，超时翻倍
            TaskPriority.NORMAL: 1.0,   # 正常优先级
            TaskPriority.HIGH: 0.8,     # 高优先级，超时缩短20%
            TaskPriority.URGENT: 0.5,   # 紧急优先级，超时减半
        }

        # 交互级别系数
        self.interaction_factors = {
            "none": 1.0,       # 无交互
            "low": 1.5,        # 低交互
            "medium": 2.0,     # 中等交互
            "high": 3.0,       # 高交互
        }

        # 自定义超时配置
        self.custom_timeouts: Dict[str, float] = {}

    def calculate_timeout(
        self,
        task_type: TaskType = TaskType.SIMPLE,
        priority: TaskPriority = TaskPriority.NORMAL,
        interaction_level: str = "none",
        task_name: Optional[str] = None,
    ) -> float:
        """
        计算超时时间

        Args:
            task_type: 任务类型
            priority: 任务优先级
            interaction_level: 交互级别
            task_name: 任务名称（用于查找自定义配置）

        Returns:
            超时时间（秒）
        """
        # 1. 检查自定义配置
        if task_name and task_name in self.custom_timeouts:
            return self.custom_timeouts[task_name]

        # 2. 获取基础超时
        base_timeout = self.base_timeouts.get(task_type, 30.0)

        # 3. 应用优先级系数
        priority_factor = self.priority_factors.get(priority, 1.0)

        # 4. 应用交互级别系数
        interaction_factor = self.interaction_factors.get(
            interaction_level,
            1.0
        )

        # 5. 计算最终超时
        timeout = base_timeout * priority_factor * interaction_factor

        # 6. 确保最小超时
        timeout = max(timeout, 1.0)

        return timeout

    def set_custom_timeout(self, task_name: str, timeout: float):
        """
        设置自定义超时

        Args:
            task_name: 任务名称
            timeout: 超时时间（秒）
        """
        self.custom_timeouts[task_name] = timeout

    def set_base_timeout(self, task_type: TaskType, timeout: float):
        """
        设置基础超时

        Args:
            task_type: 任务类型
            timeout: 超时时间（秒）
        """
        self.base_timeouts[task_type] = timeout

    def set_priority_factor(self, priority: TaskPriority, factor: float):
        """
        设置优先级系数

        Args:
            priority: 优先级
            factor: 系数
        """
        self.priority_factors[priority] = factor

    def set_interaction_factor(self, level: str, factor: float):
        """
        设置交互级别系数

        Args:
            level: 级别
            factor: 系数
        """
        self.interaction_factors[level] = factor

    def calculate_retry_timeout(
        self,
        base_timeout: float,
        retry_count: int,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> float:
        """
        计算重试超时时间（指数退避）

        Args:
            base_timeout: 基础超时
            retry_count: 当前重试次数
            max_retries: 最大重试次数
            backoff_factor: 退避因子

        Returns:
            重试超时时间
        """
        if retry_count >= max_retries:
            return base_timeout  # 达到最大重试次数，不再增加超时

        # 指数退避
        timeout = base_timeout * (backoff_factor ** retry_count)

        # 设置上限（基础超时的10倍）
        max_timeout = base_timeout * 10
        timeout = min(timeout, max_timeout)

        return timeout

    def estimate_timeout_from_history(
        self,
        historical_durations: list,
        percentile: float = 0.95,
    ) -> float:
        """
        基于历史执行时间估算超时

        Args:
            historical_durations: 历史执行时间列表
            percentile: 百分位数（默认95%）

        Returns:
            估算的超时时间
        """
        if not historical_durations:
            return 30.0  # 默认30秒

        # 排序
        sorted_durations = sorted(historical_durations)

        # 计算百分位数
        index = int(len(sorted_durations) * percentile)
        index = min(index, len(sorted_durations) - 1)

        timeout = sorted_durations[index]

        # 确保最小超时
        timeout = max(timeout, 1.0)

        return timeout

    def get_timeout_for_task(
        self,
        task: Dict,
        historical_durations: list = None,
    ) -> float:
        """
        为任务计算超时（综合方法）

        Args:
            task: 任务字典
            historical_durations: 历史执行时间（可选）

        Returns:
            超时时间
        """
        # 如果有历史数据，优先使用
        if historical_durations and len(historical_durations) >= 3:
            return self.estimate_timeout_from_history(historical_durations)

        # 否则使用多维计算
        task_type_str = task.get("type", "simple")
        task_type = TaskType(task_type_str) if task_type_str in TaskType.__members__ else TaskType.SIMPLE

        priority_str = task.get("priority", "normal")
        priority = TaskPriority(priority_str) if isinstance(priority_str, str) else TaskPriority(priority_str)

        interaction_level = task.get("interaction_level", "none")

        task_name = task.get("name")

        return self.calculate_timeout(
            task_type=task_type,
            priority=priority,
            interaction_level=interaction_level,
            task_name=task_name,
        )
