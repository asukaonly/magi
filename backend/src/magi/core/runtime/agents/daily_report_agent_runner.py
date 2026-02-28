"""
Stub runtime runner for daily report tasks.
"""
from __future__ import annotations

from ....core.logger import get_logger
from ..contracts import FactRecord
from .base_runner import BaseRuntimeAgentRunner

logger = get_logger(__name__)


class DailyReportAgentRunner(BaseRuntimeAgentRunner):
    """Stub runner: receives facts for future daily-report workflows."""

    async def handle_fact(self, fact: FactRecord) -> None:
        logger.debug(
            "DailyReportAgentRunner received fact | event_type=%s correlation_id=%s",
            fact.event_type,
            fact.correlation_id,
        )
