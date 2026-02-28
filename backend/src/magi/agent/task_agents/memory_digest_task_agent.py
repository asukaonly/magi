"""
Stub runtime task agent for memory digest tasks.
"""
from __future__ import annotations

from ...core.logger import get_logger
from ...core.runtime.contracts import FactRecord
from ...core.runtime.task_agent import TaskAgent
from ...core.runtime.types import TaskAgentType

logger = get_logger(__name__)


class MemoryDigestTaskAgent(TaskAgent):
    """Stub task-agent: receives facts for future memory-digest workflows."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_type=TaskAgentType.MEMORY_DIGEST, agent_id=agent_id)

    async def handle_fact(self, fact: FactRecord) -> None:
        logger.debug(
            "MemoryDigestTaskAgent received fact | event_type=%s correlation_id=%s",
            fact.event_type,
            fact.correlation_id,
        )
