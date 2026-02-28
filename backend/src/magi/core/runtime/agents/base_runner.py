"""
Base task-agent class for runtime agents.
"""
from __future__ import annotations

from ..task_agent import TaskAgent


class BaseRuntimeAgentRunner(TaskAgent):
    """Compatibility alias around the new TaskAgent abstraction."""

    pass
