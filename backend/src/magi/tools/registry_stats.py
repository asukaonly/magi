"""Execution statistics for registered tools."""

from __future__ import annotations

from typing import Any, Optional


class ToolExecutionStats:
    """Tool execution statistics."""

    def __init__(self):
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.failed_calls: int = 0
        self.total_execution_time: float = 0.0
        self.last_execution_time: Optional[float] = None
        self.average_execution_time: float = 0.0

    def record_call(self, success: bool, execution_time: float) -> None:
        """Record a single tool call."""
        self.total_calls += 1
        self.last_execution_time = execution_time

        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1

        self.total_execution_time += execution_time
        if self.total_calls > 0:
            self.average_execution_time = self.total_execution_time / self.total_calls

    def get_stats(self) -> dict[str, Any]:
        """Get statistics summary."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "success_rate": self.successful_calls / self.total_calls if self.total_calls > 0 else 0,
            "average_execution_time": self.average_execution_time,
            "last_execution_time": self.last_execution_time,
        }


__all__ = ["ToolExecutionStats"]
