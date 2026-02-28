"""
Stub runtime runner for memory digest tasks.
"""
from __future__ import annotations

from ....core.logger import get_logger
from ..contracts import FactRecord
from .base_runner import BaseRuntimeAgentRunner

logger = get_logger(__name__)


class MemoryDigestAgentRunner(BaseRuntimeAgentRunner):
    """Stub runner: receives facts for future memory-digest workflows."""

    async def handle_fact(self, fact: FactRecord) -> None:
        logger.debug(
            "MemoryDigestAgentRunner received fact | event_type=%s correlation_id=%s",
            fact.event_type,
            fact.correlation_id,
        )
