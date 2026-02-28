"""
RouterAgent: infinite loop dispatcher for sensor events.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from ...core.logger import get_logger
from .contracts import FactRecord
from .sensor_hub import SensorHub
from .task_agent_manager import TaskAgentManager
from .types import build_task_agent_key, get_task_agent_type_value

logger = get_logger(__name__)


class RouterAgent:
    """Continuously pulls sensor batches and dispatches facts to runtime agents."""

    def __init__(
        self,
        sensor_hub: SensorHub,
        task_agent_manager: TaskAgentManager,
        batch_size: int = 16,
        poll_timeout_seconds: float = 0.2,
    ) -> None:
        self._sensor_hub = sensor_hub
        self._task_agent_manager = task_agent_manager
        self._batch_size = batch_size
        self._poll_timeout_seconds = poll_timeout_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = {"batches": 0, "events": 0, "facts_written": 0}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("RouterAgent started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("RouterAgent stopped")

    async def _loop(self) -> None:
        while self._running:
            batch = await self._sensor_hub.get_batch(
                max_items=self._batch_size,
                timeout_seconds=self._poll_timeout_seconds,
            )
            if not batch:
                continue
            self._stats["batches"] += 1
            self._stats["events"] += len(batch)

            for sensor_event in batch:
                targets = self._task_agent_manager.resolve_targets(sensor_event)
                for target_type, target_id in targets:
                    fact = FactRecord(
                        agent_id=build_task_agent_key(target_type, target_id),
                        agent_type=get_task_agent_type_value(target_type),
                        agent_instance_id=target_id,
                        event_type=sensor_event.event_type,
                        payload=sensor_event.payload,
                        timestamp=sensor_event.timestamp,
                        correlation_id=sensor_event.correlation_id,
                    )
                    await self._task_agent_manager.add_fact_to_agent(target_type, target_id, fact)
                    self._stats["facts_written"] += 1

    def get_stats(self) -> dict:
        return dict(self._stats)
