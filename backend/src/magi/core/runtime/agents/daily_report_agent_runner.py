"""
Stub runtime task agent for daily report tasks.
"""
from __future__ import annotations

from ....core.logger import get_logger
from ..contracts import FactRecord
from ..task_agent import TaskAgent
from ..types import TaskAgentType

logger = get_logger(__name__)


class DailyReportTaskAgent(TaskAgent):
    """Stub task-agent: receives facts for future daily-report workflows."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_type=TaskAgentType.DAILY_REPORT, agent_id=agent_id)

    async def handle_fact(self, fact: FactRecord) -> None:
        logger.debug(
            "DailyReportTaskAgent received fact | event_type=%s correlation_id=%s",
            fact.event_type,
            fact.correlation_id,
        )
