"""
Runtime task agent for chat facts.
"""
from __future__ import annotations

from ..contracts import FactRecord
from .base_runner import BaseRuntimeAgentRunner
from ..types import TaskAgentType


class ChatTaskAgent(BaseRuntimeAgentRunner):
    """Consumes chat facts and delegates response execution."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)

    async def handle_fact(self, fact: FactRecord) -> None:
        if self._action_executor is None:
            return
        await self._action_executor.execute_chat_fact(fact)
