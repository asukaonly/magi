"""Agent runtime for sensor hub + router agent + runtime runners."""
from __future__ import annotations

from typing import Any

from ...awareness.event_emitter import RuntimeEventEmitter
from ...awareness.sensor_hub import SensorHub
from ...core.logger import get_logger
from .router_agent import RouterAgent
from .task_agent_manager import TaskAgentManager

logger = get_logger(__name__)


class AgentRuntime:
    """Coordinates runtime modules and agent runners lifecycle."""

    def __init__(
        self,
        sensor_hub: SensorHub,
        router_agent: RouterAgent,
        task_agent_manager: TaskAgentManager,
        event_emitter: RuntimeEventEmitter,
        post_turn_understanding_service: Any | None = None,
    ) -> None:
        self._sensor_hub = sensor_hub
        self._router_agent = router_agent
        self._task_agent_manager = task_agent_manager
        self._event_emitter = event_emitter
        self._post_turn_understanding_service = post_turn_understanding_service
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        await self._sensor_hub.start()
        await self._task_agent_manager.start_all(
            event_emitter=self._event_emitter,
            sensor_hub=self._sensor_hub,
        )
        await self._router_agent.start()
        self._running = True
        logger.info("AgentRuntime started")

    async def stop(self) -> None:
        if not self._running:
            return
        await self._router_agent.stop()
        await self._task_agent_manager.stop_all()
        await self._sensor_hub.stop()
        self._running = False
        logger.info("AgentRuntime stopped")

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "router": self._router_agent.get_stats(),
            "agents": self._task_agent_manager.get_stats(),
        }

    def get_task_agent_manager(self) -> TaskAgentManager:
        return self._task_agent_manager

    def get_sensor_hub(self) -> SensorHub:
        return self._sensor_hub

    def get_post_turn_understanding_service(self) -> Any | None:
        """Return the runtime-scoped accepted-outcome processor."""

        return self._post_turn_understanding_service
