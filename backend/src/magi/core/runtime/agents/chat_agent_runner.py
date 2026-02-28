"""
Runtime runner for chat agent facts.
"""
from __future__ import annotations

from ..contracts import FactRecord
from .base_runner import BaseRuntimeAgentRunner


class ChatAgentRunner(BaseRuntimeAgentRunner):
    """Consumes chat facts and delegates response execution."""

    async def handle_fact(self, fact: FactRecord) -> None:
        if self._action_executor is None:
            return
        await self._action_executor.execute_chat_fact(fact)
