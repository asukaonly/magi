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
        user_message_generation_getter: Callable[[], int] | None = None,
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
        self._stale_user_message_rejected_count = 0
        self._user_message_generation_getter = user_message_generation_getter
        self._sensor_hub = None
        self._chat_clear_lock = asyncio.Lock()
        self._chat_work_resumed = asyncio.Event()
        self._chat_work_resumed.set()
        self._chat_pause_depth = 0
        self._chat_quiesce_task: asyncio.Task[None] | None = None

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

    async def pause_chat_work_and_cancel_all(self) -> int:
        """Pause chat admission and cancel every active or queued chat run."""
        async with self._chat_clear_lock:
            self._chat_pause_depth += 1
            self._chat_work_resumed.clear()
            if self._chat_pause_depth == 1:
                chat_keys = [
                    key
                    for key in self._agents
                    if self._parse_agent_key(key)[0] == TaskAgentType.CHAT.value
                ]
                agents = [self._agents.pop(key) for key in chat_keys]
                for key in chat_keys:
                    self._instance_metadata.pop(key, None)
                self._chat_quiesce_task = asyncio.create_task(
                    self._quiesce_chat_agents(agents),
                    name="task-agent-manager:memory-clear-chat-quiesce",
                )
            task = self._chat_quiesce_task
            cancelled_count = len(chat_keys) if self._chat_pause_depth == 1 else 0
        if task is not None:
            await asyncio.shield(task)
        return cancelled_count

    async def resume_chat_work(self) -> None:
        """Resume chat admission after a destructive memory clear."""
        async with self._chat_clear_lock:
            self._chat_pause_depth = max(0, self._chat_pause_depth - 1)
            if self._chat_pause_depth > 0:
                return
            quiesce_task = self._chat_quiesce_task
        if quiesce_task is not None:
            try:
                await asyncio.shield(quiesce_task)
            except Exception:
                logger.exception("Chat quiesce failed while resuming after memory clear")
        async with self._chat_clear_lock:
            if self._chat_pause_depth > 0:
                return
            try:
                if self._running:
                    await self._ensure_agent_unlocked(TaskAgentType.CHAT, "default")
            finally:
                self._chat_quiesce_task = None
                self._chat_work_resumed.set()

    async def _quiesce_chat_agents(self, agents: list[TaskAgent]) -> None:
        results = await asyncio.gather(
            *(self._cancel_and_stop_chat_agent(agent) for agent in agents),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError(
                f"Failed to stop {len(failures)} chat agent(s) before memory clear"
            ) from failures[0]

    @staticmethod
    async def _cancel_and_stop_chat_agent(agent: TaskAgent) -> None:
        cancel_handler = getattr(agent, "request_session_cancel", None)
        cancel_failure: BaseException | None = None
        if callable(cancel_handler):
            try:
                await cancel_handler(
                    session_id=agent.agent_id,
                    requested_by="system",
                    reason="memory_clear",
                    anchor_turn_id=None,
                )
            except BaseException as exc:
                cancel_failure = exc
                logger.exception(
                    "Failed to request chat run cancellation before memory clear | key=%s",
                    agent.runtime_key,
                )
        try:
            await agent.stop()
        except BaseException as stop_failure:
            if cancel_failure is not None:
                logger.error(
                    "Chat cancellation and stop both failed before memory clear | key=%s",
                    agent.runtime_key,
                    exc_info=(
                        type(cancel_failure),
                        cancel_failure,
                        cancel_failure.__traceback__,
                    ),
                )
            raise stop_failure
        if cancel_failure is not None:
            raise RuntimeError(
                "Failed to cancel chat run before memory clear"
            ) from cancel_failure

    async def ensure_agent(self, agent_type: TaskAgentType | str, agent_id: str) -> TaskAgent:
        if get_task_agent_type_value(agent_type) == TaskAgentType.CHAT.value:
            while True:
                await self._chat_work_resumed.wait()
                async with self._chat_clear_lock:
                    if self._chat_pause_depth == 0:
                        return await self._ensure_agent_unlocked(agent_type, agent_id)
        return await self._ensure_agent_unlocked(agent_type, agent_id)

    async def _ensure_agent_unlocked(
        self,
        agent_type: TaskAgentType | str,
        agent_id: str,
    ) -> TaskAgent:
        key = build_task_agent_key(agent_type, agent_id)
        if key in self._agents:
            self._update_instance_metadata(key)
            return self._agents[key]

        if not self._is_core_instance(agent_type, agent_id):
            await self._maybe_evict_idle_instances()

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
            try:
                await agent.start(
                    self._event_emitter,
                    task_agent_manager=self,
                    sensor_hub=self._sensor_hub,
                )
            except BaseException:
                self._agents.pop(key, None)
                self._instance_metadata.pop(key, None)
                raise
        logger.info(f"TaskAgent ensured | key={key}")
        return agent

    async def add_fact_to_agent(self, agent_type: TaskAgentType | str, agent_id: str, fact: FactRecord) -> bool:
        """Add fact to agent, returns True if successful, False if rejected."""
        try:
            if get_task_agent_type_value(agent_type) == TaskAgentType.CHAT.value:
                while True:
                    await self._chat_work_resumed.wait()
                    async with self._chat_clear_lock:
                        if self._chat_pause_depth != 0:
                            continue
                        if self._is_stale_user_message(fact):
                            self._stale_user_message_rejected_count += 1
                            logger.info(
                                "Rejected stale user-message fact after memory clear | "
                                "fact_generation=%s current_generation=%s",
                                fact.user_message_generation,
                                self.current_user_message_generation(),
                            )
                            return False
                        agent = await self._ensure_agent_unlocked(agent_type, agent_id)
                        result = await agent.add_fact(fact)
                        break
            else:
                agent = await self._ensure_agent_unlocked(agent_type, agent_id)
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
            "stale_user_message_rejected_count": self._stale_user_message_rejected_count,
        }

    def current_user_message_generation(self) -> int | None:
        """Return the active chat ingress generation when one is configured."""
        if self._user_message_generation_getter is None:
            return None
        return int(self._user_message_generation_getter())

    def _is_stale_user_message(self, fact: FactRecord) -> bool:
        if fact.event_type != EventTypes.USER_MESSAGE:
            return False
        current_generation = self.current_user_message_generation()
        if current_generation is None:
            return False
        if fact.user_message_generation is None:
            return True
        return int(fact.user_message_generation) != current_generation

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

    async def _maybe_evict_idle_instances(self) -> None:
        """Evict the oldest idle instance if at capacity, to make room for a new one."""
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
            agent = self._agents.pop(oldest_key, None)
            self._instance_metadata.pop(oldest_key, None)
            if agent is not None:
                await agent.stop()
            logger.info(f"Evicted oldest idle instance to make room | key={oldest_key}")

    def _parse_agent_key(self, key: str) -> tuple[str, str]:
        """Parse agent key back to (type, id)."""
        parts = key.split(":", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "chat", key
