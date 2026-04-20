"""TaskAgentManager for hybrid lifecycle multi-instance runtime."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ...awareness.contracts import SensorEvent
from ...events.events import EventTypes
from ...core.logger import get_logger
from .contracts import FactRecord
from .task_agent import TaskAgent
from .types import TaskAgentType, build_task_agent_key, get_task_agent_type_value

logger = get_logger(__name__)


@dataclass
class InstanceMetadata:
    """Metadata for tracking agent instances."""
    created_at: float
    last_active_at: float
    pending_queue_size: int = 0


class TaskAgentManager:
    """Manages persistent and dynamic task-agent instances."""

    def __init__(
        self,
        create_chat_agent: Callable[[str], TaskAgent],
        create_default_agent: Optional[Callable[[str, str], TaskAgent]] = None,
        idle_ttl_seconds: float = 1800.0,
        max_dynamic_instances: int = 100,
        janitor_interval_seconds: float = 60.0,
    ) -> None:
        self._create_chat_agent = create_chat_agent
        self._create_default_agent = create_default_agent
        self._agents: dict[str, TaskAgent] = {}
        self._instance_metadata: dict[str, InstanceMetadata] = {}
        self._running = False
        self._event_emitter = None
        self._core_instances = (
            (TaskAgentType.CHAT, "default"),
        )
        self._idle_ttl_seconds = idle_ttl_seconds
        self._max_dynamic_instances = max_dynamic_instances
        self._janitor_interval_seconds = janitor_interval_seconds
        self._janitor_task: Optional[asyncio.Task] = None
        self._enqueue_rejected_count = 0
        self._sensor_hub = None

    async def start_all(self, event_emitter, sensor_hub=None) -> None:
        if self._running:
            return
        self._running = True
        self._event_emitter = event_emitter
        self._sensor_hub = sensor_hub
        for agent_type, agent_id in self._core_instances:
            await self.ensure_agent(agent_type, agent_id)
        self._janitor_task = asyncio.create_task(self._janitor_loop())
        logger.info(f"TaskAgentManager started | janitor_interval={self._janitor_interval_seconds}s")

    async def stop_all(self) -> None:
        if self._janitor_task is not None:
            self._janitor_task.cancel()
            try:
                await self._janitor_task
            except asyncio.CancelledError:
                pass
            self._janitor_task = None
        for agent in list(self._agents.values()):
            await agent.stop()
        self._agents.clear()
        self._instance_metadata.clear()
        self._running = False
        self._event_emitter = None
        self._sensor_hub = None

    async def ensure_agent(self, agent_type: TaskAgentType | str, agent_id: str) -> TaskAgent:
        key = build_task_agent_key(agent_type, agent_id)
        if key in self._agents:
            self._update_instance_metadata(key)
            return self._agents[key]

        if not self._is_core_instance(agent_type, agent_id):
            self._maybe_evict_idle_instances()

        if len(self._agents) >= self._max_dynamic_instances + len(self._core_instances):
            logger.warning(f"TaskAgentManager at max capacity | max={self._max_dynamic_instances}")
            raise RuntimeError(f"Maximum dynamic instances reached: {self._max_dynamic_instances}")

        agent = self._create_agent_instance(agent_type, agent_id)
        self._agents[key] = agent
        now = time.time()
        self._instance_metadata[key] = InstanceMetadata(
            created_at=now,
            last_active_at=now,
            pending_queue_size=0,
        )
        if self._running:
            await agent.start(
                self._event_emitter,
                task_agent_manager=self,
                sensor_hub=self._sensor_hub,
            )
        logger.info(f"TaskAgent ensured | key={key}")
        return agent

    async def add_fact_to_agent(self, agent_type: TaskAgentType | str, agent_id: str, fact: FactRecord) -> bool:
        """Add fact to agent, returns True if successful, False if rejected."""
        try:
            agent = await self.ensure_agent(agent_type, agent_id)
            result = await agent.add_fact(fact)
            key = build_task_agent_key(agent_type, agent_id)
            self._update_instance_metadata(key)
            return result
        except Exception as exc:
            self._enqueue_rejected_count += 1
            logger.warning(f"Failed to add fact to agent | error={exc}")
            return False

    def resolve_targets(self, sensor_event: SensorEvent) -> list[tuple[TaskAgentType | str, str]]:
        payload = sensor_event.payload
        target_type = payload.get("target_task_agent_type")
        target_id = payload.get("target_task_agent_id")
        if target_type:
            resolved_type = self._coerce_agent_type(str(target_type))
            resolved_id = str(target_id or "default")
            return [(resolved_type, resolved_id)]

        if sensor_event.event_type == EventTypes.USER_MESSAGE:
            session_id = str(payload.get("session_id") or "").strip()
            if not session_id:
                raise ValueError("USER_MESSAGE requires session_id for chat routing")
            return [(TaskAgentType.CHAT, session_id)]

        return [(TaskAgentType.CHAT, "default")]

    def get_agent(self, agent_type: TaskAgentType | str, agent_id: str) -> Optional[TaskAgent]:
        return self._agents.get(build_task_agent_key(agent_type, agent_id))

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "instances": {key: agent.get_stats() for key, agent in self._agents.items()},
            "instance_count": len(self._agents),
            "max_dynamic_instances": self._max_dynamic_instances,
            "idle_ttl_seconds": self._idle_ttl_seconds,
            "enqueue_rejected_count": self._enqueue_rejected_count,
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

    def _is_core_instance(self, agent_type: TaskAgentType | str, agent_id: str) -> bool:
        for core_type, core_id in self._core_instances:
            if get_task_agent_type_value(core_type) == get_task_agent_type_value(agent_type) and core_id == agent_id:
                return True
        return False

    def _update_instance_metadata(self, key: str) -> None:
        if key in self._instance_metadata:
            meta = self._instance_metadata[key]
            meta.last_active_at = time.time()
            agent = self._agents.get(key)
            if agent:
                meta.pending_queue_size = agent._fact_queue.qsize()

    async def _janitor_loop(self) -> None:
        """Periodically clean up idle instances."""
        while self._running:
            try:
                await asyncio.sleep(self._janitor_interval_seconds)
                await self._cleanup_idle_instances()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Janitor loop error | error={exc}")

    async def _cleanup_idle_instances(self) -> None:
        """Stop and remove instances that have been idle too long."""
        now = time.time()
        keys_to_remove = []

        for key, meta in self._instance_metadata.items():
            agent_type, agent_id = self._parse_agent_key(key)
            if self._is_core_instance(agent_type, agent_id):
                continue

            idle_time = now - meta.last_active_at
            agent = self._agents.get(key)
            queue_size = agent._fact_queue.qsize() if agent else 0

            if idle_time > self._idle_ttl_seconds and queue_size == 0:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            agent = self._agents.pop(key, None)
            self._instance_metadata.pop(key, None)
            if agent:
                await agent.stop()
                logger.info(f"TaskAgent recycled | key={key}")

        if keys_to_remove:
            logger.info(f"Janitor recycled {len(keys_to_remove)} idle instances")

    def _maybe_evict_idle_instances(self) -> None:
        """Evict oldest idle instance if at capacity."""
        dynamic_count = len(self._agents) - len(self._core_instances)
        if dynamic_count < self._max_dynamic_instances:
            return

        oldest_key = None
        oldest_time = float("inf")

        for key, meta in self._instance_metadata.items():
            agent_type, agent_id = self._parse_agent_key(key)
            if self._is_core_instance(agent_type, agent_id):
                continue

            agent = self._agents.get(key)
            queue_size = agent._fact_queue.qsize() if agent else 0

            if queue_size == 0 and meta.last_active_at < oldest_time:
                oldest_time = meta.last_active_at
                oldest_key = key

        if oldest_key:
            logger.warning(f"Evicting oldest idle instance to make room | key={oldest_key}")

    def _parse_agent_key(self, key: str) -> tuple[str, str]:
        """Parse agent key back to (type, id)."""
        parts = key.split(":", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "chat", key
