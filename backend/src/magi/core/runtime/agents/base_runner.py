"""
Base runner for runtime agents.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from ....core.logger import get_logger
from ..fact_store import FactStore
from ..contracts import FactRecord

logger = get_logger(__name__)


class BaseRuntimeAgentRunner:
    """Common lifecycle for runtime agent runners."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._fact_store: Optional[FactStore] = None
        self._action_executor = None

    async def start(self, fact_store: FactStore, action_executor) -> None:
        if self._running:
            return
        self._fact_store = fact_store
        self._action_executor = action_executor
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        if self._fact_store is None:
            return
        queue = self._fact_store.get_queue(self.agent_id)
        while self._running:
            try:
                fact = await asyncio.wait_for(queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            await self.handle_fact(fact)

    async def handle_fact(self, fact: FactRecord) -> None:
        raise NotImplementedError
