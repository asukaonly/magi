"""
超时计算器 - 多维度超时计算

根据任务类型、优先级、交互级别计算超时时间
"""
from enum import Enum
from .task_database import TaskType, TaskPriority


class InteractionLevel(Enum):
    """交互级别"""
    NONE = "none"          # 无交互，纯后台计算
    LOW = "low"            # 低交互，偶尔通知
    MEDIUM = "medium"      # 中等交互，需要确认
    HIGH = "high"          # 高交互，需要频繁用户输入


class TimeoutCalculator:
    """
    超时计算器

    超时计算公式：
    timeout = base_timeout × priority_factor × type_factor × interaction_factor
    """

    # 基础超时时间（秒）
    BASE_TIMEOUT = 60.0

    # 优先级因子
    PRIORITY_FACTORS = {
        TaskPriority.LOW: 2.0,        # 低优先级任务可以运行更久
        TaskPriority.NORMAL: 1.0,     # 正常优先级
        TaskPriority.HIGH: 0.8,       # 高优先级快速处理
        TaskPriority.URGENT: 0.5,     # 紧急任务快速失败
        TaskPriority.EMERGENCY: 0.3,  # 紧急任务极速失败
    }

    # 任务类型因子
    TYPE_FACTORS = {
        TaskType.QUERY: 0.5,          # 查询类快速响应
        TaskType.COMPUTATION: 3.0,    # 计算类需要更长时间
        TaskType.INTERACTIVE: 2.0,    # 交互类等待用户
        TaskType.BATCH: 5.0,          # 批处理类允许最长时间
    }

    # 交互级别因子
    INTERACTION_FACTORS = {
        InteractionLevel.NONE: 1.0,    # 无交互
        InteractionLevel.LOW: 1.2,     # 低交互
        InteractionLevel.MEDIUM: 1.5,  # 中等交互
        InteractionLevel.HIGH: 2.0,    # 高交互，需要等待用户输入
    }

    @classmethod
    def calculate(
        cls,
        task_type: TaskType = TaskType.QUERY,
        priority: TaskPriority = TaskPriority.NORMAL,
        interaction_level: InteractionLevel = InteractionLevel.NONE,
        base_timeout: float = None,
    ) -> float:
        """
        计算超时时间

        Args:
            task_type: 任务类型
            priority: 任务优先级
            interaction_level: 交互级别
            base_timeout: 自定义基础超时

        Returns:
            超时时间（秒）
        """
        base = base_timeout or cls.BASE_TIMEOUT

        priority_factor = cls.PRIORITY_FACTORS.get(priority, 1.0)
        type_factor = cls.TYPE_FACTORS.get(task_type, 1.0)
        interaction_factor = cls.INTERACTION_FACTORS.get(interaction_level, 1.0)

        timeout = base * priority_factor * type_factor * interaction_factor

        # 最小超时10秒，最大超时300秒（5分钟）
        return max(10.0, min(timeout, 300.0))

    @classmethod
    def calculate_for_task(cls, task_data: dict) -> float:
        """
        根据任务数据计算超时

        Args:
            task_data: 任务数据字典，可能包含type、priority、interaction_level

        Returns:
            超时时间（秒）
        """
        # 从任务数据中提取参数
        type_str = task_data.get("type", TaskType.QUERY.value)
        priority_value = task_data.get("priority", TaskPriority.NORMAL.value)
        interaction_str = task_data.get("interaction_level", InteractionLevel.NONE.value)

        # 转换为枚举
        try:
            task_type = TaskType(type_str)
        except ValueError:
            task_type = TaskType.QUERY

        try:
            priority = TaskPriority(priority_value)
        except ValueError:
            priority = TaskPriority.NORMAL

        try:
            interaction_level = InteractionLevel(interaction_str)
        except ValueError:
            interaction_level = InteractionLevel.NONE

        return cls.calculate(task_type, priority, interaction_level)
