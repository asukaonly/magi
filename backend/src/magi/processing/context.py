"""
Context perception and processing
"""
import time
from typing import Dict, Any, List
from .base import processingContext


class ContextManager:
    """
    Context Manager

    Collects and manages contextual information.
    """

    def __init__(self):
        """Initialize the Context Manager."""
        self._context = processingContext(
            user_status={},
            system_status={},
            recent_tasks=[],
        )

        # Context configuration
        self.max_recent_tasks = 20  # Keep at most 20 recent tasks
        self.context_ttl = 3600  # Context TTL (seconds)

    async def collect(self) -> processingContext:
        """
        Collect contextual information.

        Returns:
            Current context
        """
        # Update timestamp
        self._context.current_time = time.time()

        # Collect user status
        self._context.user_status = await self._collect_user_status()

        # Collect system status
        self._context.system_status = await self._collect_system_status()

        return self._context

    async def update_after_task(self, task: Dict, result: Any):
        """
        Update context after task execution.

        Args:
            task: Task description
            result: Execution result
        """
        # Add to recent tasks
        task_record = {
            "task": task,
            "result": result,
            "timestamp": time.time(),
        }

        self._context.recent_tasks.append(task_record)

        # Limit quantity
        if len(self._context.recent_tasks) > self.max_recent_tasks:
            self._context.recent_tasks.pop(0)

    async def should_notify(self) -> bool:
        """
        Determine whether the user should be notified.

        Returns:
            Whether to notify
        """
        # Decide based on user status
        user_status = self._context.user_status

        # If user is busy, don't notify
        if user_status.get("busy", False):
            return False

        # If it's late night, reduce notifications
        current_hour = time.localtime(self._context.current_time).tm_hour
        if current_hour >= 23 or current_hour <= 6:
            return False

        return True

    async def adjust_task_priority(self, base_priority: int) -> int:
        """
        Adjust task priority based on context.

        Args:
            base_priority: Base priority

        Returns:
            Adjusted priority
        """
        # If system load is high, lower priority
        system_status = self._context.system_status
        cpu_usage = system_status.get("cpu_usage", 0)

        if cpu_usage > 80:
            return max(base_priority - 1, 0)

        return base_priority

    async def _collect_user_status(self) -> Dict[str, Any]:
        """Collect user status."""
        # Simplified: return default status
        # Actual implementation could pull from calendar, status apps, etc.
        return {
            "busy": False,
            "active": True,
        }

    async def _collect_system_status(self) -> Dict[str, Any]:
        """Collect system status."""
        # Simplified: return basic status
        import psutil
        return {
            "cpu_usage": psutil.cpu_percent(),
            "memory_usage": psutil.virtual_memory().percent,
        }
