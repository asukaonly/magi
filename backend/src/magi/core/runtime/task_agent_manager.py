"""
TaskAgentManager for hybrid lifecycle multi-instance runtime.
"""
from __future__ import annotations

from typing import Callable, Optional

from ...events.events import EventTypes
from ...core.logger import get_logger
from .contracts import FactRecord, SensorEvent
from .task_agent import TaskAgent
from .types import TaskAgentType, build_task_agent_key, get_task_agent_type_value

logger = get_logger(__name__)


class TaskAgentManager:
    """Manages persistent and dynamic task-agent instances."""

    def __init__(
        self,
        create_chat_agent: Callable[[str], TaskAgent],
        create_default_agent: Optional[Callable[[str, str], TaskAgent]] = None,
    ) -> None:
        self._create_chat_agent = create_chat_agent
        self._create_default_agent = create_default_agent
        self._agents: dict[str, TaskAgent] = {}
        self._running = False
        self._action_executor = None
        self._core_instances = (
            (TaskAgentType.CHAT, "default"),
        )

    async def start_all(self, action_executor) -> None:
        if self._running:
            return
        self._running = True
        self._action_executor = action_executor
        for agent_type, agent_id in self._core_instances:
            await self.ensure_agent(agent_type, agent_id)

    async def stop_all(self) -> None:
        for agent in list(self._agents.values()):
            await agent.stop()
        self._agents.clear()
        self._running = False
        self._action_executor = None

    async def ensure_agent(self, agent_type: TaskAgentType | str, agent_id: str) -> TaskAgent:
        key = build_task_agent_key(agent_type, agent_id)
        if key in self._agents:
            return self._agents[key]

        agent = self._create_agent_instance(agent_type, agent_id)
        self._agents[key] = agent
        if self._running:
            await agent.start(self._action_executor)
        logger.info(f"TaskAgent ensured | key={key}")
        return agent

    async def add_fact_to_agent(self, agent_type: TaskAgentType | str, agent_id: str, fact: FactRecord) -> None:
        agent = await self.ensure_agent(agent_type, agent_id)
        await agent.add_fact(fact)

    def resolve_targets(self, sensor_event: SensorEvent) -> list[tuple[TaskAgentType | str, str]]:
        payload = sensor_event.payload
        target_type = payload.get("target_task_agent_type")
        target_id = payload.get("target_task_agent_id")
        if target_type:
            resolved_type = self._coerce_agent_type(str(target_type))
            resolved_id = str(target_id or "default")
            return [(resolved_type, resolved_id)]

        if sensor_event.event_type == EventTypes.USER_MESSAGE:
            chat_id = str(payload.get("target_task_agent_id") or payload.get("user_id") or "default")
            return [(TaskAgentType.CHAT, chat_id)]

        return [(TaskAgentType.CHAT, "default")]

    def get_agent(self, agent_type: TaskAgentType | str, agent_id: str) -> Optional[TaskAgent]:
        return self._agents.get(build_task_agent_key(agent_type, agent_id))

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "instances": {key: agent.get_stats() for key, agent in self._agents.items()},
        }

    def list_instance_keys(self) -> list[str]:
        return sorted(self._agents.keys())

    def _create_agent_instance(self, agent_type: TaskAgentType | str, agent_id: str) -> TaskAgent:
        normalized_type = self._coerce_agent_type(get_task_agent_type_value(agent_type))
        if normalized_type == TaskAgentType.CHAT:
            return self._create_chat_agent(agent_id)
        if self._create_default_agent is None:
            raise ValueError(f"Unsupported task agent type: {agent_type}")
        return self._create_default_agent(get_task_agent_type_value(agent_type), agent_id)

    def _coerce_agent_type(self, type_value: str) -> TaskAgentType | str:
        for candidate in TaskAgentType:
            if candidate.value == type_value:
                return candidate
        return type_value
