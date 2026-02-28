"""
Default runtime task agent for non-specialized task types.
"""
from __future__ import annotations

from ...core.logger import get_logger
from ...core.runtime.contracts import FactRecord
from ...core.runtime.task_agent import TaskAgent

logger = get_logger(__name__)


class DefaultTaskAgent(TaskAgent):
    """Fallback implementation for task-agent types without specialization."""

    async def handle_fact(self, fact: FactRecord) -> None:
        logger.debug(
            "DefaultTaskAgent received fact | key=%s event_type=%s correlation_id=%s",
            self.runtime_key,
            fact.event_type,
            fact.correlation_id,
        )
