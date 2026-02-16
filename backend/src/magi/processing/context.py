"""
contextPerceptionprocess
"""
import time
from typing import Dict, Any, List
from .base import processingContext


class ContextManager:
    """
    context管理器

    收集and管理contextinfo
    """

    def __init__(self):
        """initializecontext管理器"""
        self._context = processingContext(
            user_status={},
            system_status={},
            recent_tasks=[],
        )

        # contextConfiguration
        self.max_recent_tasks = 20  # 最多保留20个最近任务
        self.context_ttl = 3600  # contextvalid期（seconds）

    async def collect(self) -> processingContext:
        """
        收集contextinfo

        Returns:
            currentcontext
        """
        # updated at戳
        self._context.current_time = time.time()

        # 收集userState
        self._context.user_status = await self._collect_user_status()

        # 收集系统State
        self._context.system_status = await self._collect_system_status()

        return self._context

    async def update_after_task(self, task: Dict, result: Any):
        """
        任务Execute后updatecontext

        Args:
            task: 任务Description
            result: Execution result
        """
        # add到最近任务
        task_record = {
            "task": task,
            "result": result,
            "timestamp": time.time(),
        }

        self._context.recent_tasks.append(task_record)

        # limitationquantity
        if len(self._context.recent_tasks) > self.max_recent_tasks:
            self._context.recent_tasks.pop(0)

    async def should_notify(self) -> bool:
        """
        判断is not应该notifyuser

        Returns:
            is not应该notify
        """
        # 基于userState判断
        user_status = self._context.user_status

        # 如果user忙碌，不notify
        if user_status.get("busy", False):
            return False

        # 如果is深夜，减少notify
        current_hour = time.localtime(self._context.current_time).tm_hour
        if current_hour >= 23 or current_hour <= 6:
            return False

        return True

    async def adjust_task_priority(self, base_priority: int) -> int:
        """
        根据context调整任务priority

        Args:
            base_priority: basepriority

        Returns:
            调整后的priority
        """
        # 如果系统负载高，降低priority
        system_status = self._context.system_status
        cpu_usage = system_status.get("cpu_usage", 0)

        if cpu_usage > 80:
            return max(base_priority - 1, 0)

        return base_priority

    async def _collect_user_status(self) -> Dict[str, Any]:
        """收集userState"""
        # 简化版：ReturndefaultState
        # 实际Implementation可以从日历、State应用等get
        return {
            "busy": False,
            "active": True,
        }

    async def _collect_system_status(self) -> Dict[str, Any]:
        """收集系统State"""
        # 简化版：Return基本State
        import psutil
        return {
            "cpu_usage": psutil.cpu_percent(),
            "memory_usage": psutil.virtual_memory().percent,
        }
