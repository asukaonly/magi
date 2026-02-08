"""
上下文感知处理
"""
import time
from typing import Dict, Any, List
from .base import ProcessingContext


class ContextManager:
    """
    上下文管理器

    收集和管理上下文信息
    """

    def __init__(self):
        """初始化上下文管理器"""
        self._context = ProcessingContext(
            user_status={},
            system_status={},
            recent_tasks=[],
        )

        # 上下文配置
        self.max_recent_tasks = 20  # 最多保留20个最近任务
        self.context_ttl = 3600  # 上下文有效期（秒）

    async def collect(self) -> ProcessingContext:
        """
        收集上下文信息

        Returns:
            当前上下文
        """
        # 更新时间戳
        self._context.current_time = time.time()

        # 收集用户状态
        self._context.user_status = await self._collect_user_status()

        # 收集系统状态
        self._context.system_status = await self._collect_system_status()

        return self._context

    async def update_after_task(self, task: Dict, result: Any):
        """
        任务执行后更新上下文

        Args:
            task: 任务描述
            result: 执行结果
        """
        # 添加到最近任务
        task_record = {
            "task": task,
            "result": result,
            "timestamp": time.time(),
        }

        self._context.recent_tasks.append(task_record)

        # 限制数量
        if len(self._context.recent_tasks) > self.max_recent_tasks:
            self._context.recent_tasks.pop(0)

    async def should_notify(self) -> bool:
        """
        判断是否应该通知用户

        Returns:
            是否应该通知
        """
        # 基于用户状态判断
        user_status = self._context.user_status

        # 如果用户忙碌，不通知
        if user_status.get("busy", False):
            return False

        # 如果是深夜，减少通知
        current_hour = time.localtime(self._context.current_time).tm_hour
        if current_hour >= 23 or current_hour <= 6:
            return False

        return True

    async def adjust_task_priority(self, base_priority: int) -> int:
        """
        根据上下文调整任务优先级

        Args:
            base_priority: 基础优先级

        Returns:
            调整后的优先级
        """
        # 如果系统负载高，降低优先级
        system_status = self._context.system_status
        cpu_usage = system_status.get("cpu_usage", 0)

        if cpu_usage > 80:
            return max(base_priority - 1, 0)

        return base_priority

    async def _collect_user_status(self) -> Dict[str, Any]:
        """收集用户状态"""
        # 简化版：返回默认状态
        # 实际实现可以从日历、状态应用等获取
        return {
            "busy": False,
            "active": True,
        }

    async def _collect_system_status(self) -> Dict[str, Any]:
        """收集系统状态"""
        # 简化版：返回基本状态
        import psutil
        return {
            "cpu_usage": psutil.cpu_percent(),
            "memory_usage": psutil.virtual_memory().percent,
        }
