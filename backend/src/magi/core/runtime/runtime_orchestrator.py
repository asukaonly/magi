"""
Runtime orchestrator for sensor hub + router agent + runtime runners.
"""
from __future__ import annotations

from ...core.logger import get_logger
from .sensor_hub import SensorHub
from .router_agent import RouterAgent
from .agent_registry import AgentRegistry
from .fact_store import FactStore
from .action_executor import ActionExecutor

logger = get_logger(__name__)


class RuntimeOrchestrator:
    """Coordinates runtime modules and agent runners lifecycle."""

    def __init__(
        self,
        sensor_hub: SensorHub,
        router_agent: RouterAgent,
        agent_registry: AgentRegistry,
        fact_store: FactStore,
        action_executor: ActionExecutor,
    ) -> None:
        self._sensor_hub = sensor_hub
        self._router_agent = router_agent
        self._agent_registry = agent_registry
        self._fact_store = fact_store
        self._action_executor = action_executor
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        await self._sensor_hub.start()
        await self._agent_registry.start_all(
            fact_store=self._fact_store,
            action_executor=self._action_executor,
        )
        await self._router_agent.start()
        self._running = True
        logger.info("RuntimeOrchestrator started")

    async def stop(self) -> None:
        if not self._running:
            return
        await self._router_agent.stop()
        await self._agent_registry.stop_all()
        await self._sensor_hub.stop()
        self._running = False
        logger.info("RuntimeOrchestrator stopped")

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "router": self._router_agent.get_stats(),
            "facts": self._fact_store.get_counts(),
            "agents": self._agent_registry.list_runner_ids(),
        }
