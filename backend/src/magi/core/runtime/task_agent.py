"""
TaskAgent base abstraction for multi-instance runtime.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from ...core.logger import get_logger
from .contracts import FactRecord
from .types import TaskAgentType, build_task_agent_key

logger = get_logger(__name__)


class TaskAgent:
    """Self-looping task agent instance with its own fact queue."""

    def __init__(self, agent_type: TaskAgentType, agent_id: str) -> None:
        self.agent_type = agent_type
        self.agent_id = agent_id
        self.runtime_key = build_task_agent_key(agent_type, agent_id)
        self._fact_queue: asyncio.Queue[FactRecord] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._action_executor = None
        self._processed = 0

    async def start(self, action_executor) -> None:
        if self._running:
            return
        self._action_executor = action_executor
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"TaskAgent started | key={self.runtime_key}")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"TaskAgent stopped | key={self.runtime_key}")

    async def add_fact(self, fact: FactRecord) -> None:
        await self._fact_queue.put(fact)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                fact = await asyncio.wait_for(self._fact_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            await self.handle_fact(fact)
            self._processed += 1

    async def handle_fact(self, fact: FactRecord) -> None:
        raise NotImplementedError

    def get_stats(self) -> dict:
        return {
            "agent_type": self.agent_type.value,
            "agent_id": self.agent_id,
            "runtime_key": self.runtime_key,
            "queue_size": self._fact_queue.qsize(),
            "processed": self._processed,
            "running": self._running,
        }
