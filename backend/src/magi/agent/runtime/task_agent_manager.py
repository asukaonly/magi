"""TaskAgentManager for hybrid lifecycle multi-instance runtime."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from ...awareness.contracts import SensorEvent
from ...events.events import EventTypes
from ...core.logger import get_logger
from .chat_message_delete import (
    ChatMessageDeleteCoordinator,
    ChatMessageDeleteHold,
)
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


@dataclass(frozen=True, slots=True)
class _UserMessageDeliveryIdentity:
    """Durable identity for one physical user-message delivery attempt."""

    turn_id: str
    delivery_attempt_no: int
    runtime_command_id: int


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
        user_message_scope_blocker: Callable[..., Awaitable[bool]] | None = None,
        user_message_delivery_admitter: Callable[..., Awaitable[bool]] | None = None,
        runtime_command_acknowledger: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self._create_chat_agent = create_chat_agent
        self._create_default_agent = create_default_agent
        self._agents: dict[str, TaskAgent] = {}
        self._instance_metadata: dict[str, InstanceMetadata] = {}
        self._running = False
        self._event_emitter = None
        self._core_instances = ((TaskAgentType.CHAT, "default"),)
        self._idle_ttl_seconds = idle_ttl_seconds
        self._max_dynamic_instances = max_dynamic_instances
        self._janitor_interval_seconds = janitor_interval_seconds
        self._janitor_task: Optional[asyncio.Task] = None
        self._enqueue_rejected_count = 0
        self._stale_user_message_rejected_count = 0
        self._user_message_generation_getter = user_message_generation_getter
        self._user_message_scope_blocker = user_message_scope_blocker
        self._blocked_user_message_rejected_count = 0
        self._user_message_delivery_admitter = user_message_delivery_admitter
        self._runtime_command_acknowledger = runtime_command_acknowledger
        self._superseded_user_message_count = 0
        self._sensor_hub = None
        self._chat_clear_lock = asyncio.Lock()
        self._chat_work_resumed = asyncio.Event()
        self._chat_work_resumed.set()
        self._chat_pause_depth = 0
        self._chat_quiesce_task: asyncio.Task[None] | None = None
        self._chat_session_quiesce_events: dict[str, asyncio.Event] = {}
        self._chat_message_delete = ChatMessageDeleteCoordinator(
            chat_clear_lock=self._chat_clear_lock,
            agents=self._agents,
            instance_metadata=self._instance_metadata,
            session_quiesce_events=self._chat_session_quiesce_events,
            cancel_and_stop=self._cancel_and_stop_chat_agent,
        )

    async def start_all(self, event_emitter, sensor_hub=None) -> None:
        if self._running:
            return
        self._running = True
        self._event_emitter = event_emitter
        self._sensor_hub = sensor_hub
        for agent_type, agent_id in self._core_instances:
            await self.ensure_agent(agent_type, agent_id)
        self._janitor_task = asyncio.create_task(self._janitor_loop())
        logger.info(
            f"TaskAgentManager started | janitor_interval={self._janitor_interval_seconds}s"
        )

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
                quiescing_sessions = set(self._chat_session_quiesce_events)
                session_quiesce_events = list(
                    self._chat_session_quiesce_events.values()
                )
                chat_keys = [
                    key
                    for key in self._agents
                    if (
                        self._parse_agent_key(key)[0] == TaskAgentType.CHAT.value
                        and self._parse_agent_key(key)[1] not in quiescing_sessions
                    )
                ]
                agents = [self._agents.pop(key) for key in chat_keys]
                for key in chat_keys:
                    self._instance_metadata.pop(key, None)
                self._chat_quiesce_task = asyncio.create_task(
                    self._quiesce_chat_agents(
                        agents,
                        session_quiesce_events=session_quiesce_events,
                    ),
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

    async def _quiesce_chat_agents(
        self,
        agents: list[TaskAgent],
        *,
        session_quiesce_events: list[asyncio.Event] | None = None,
    ) -> None:
        initial_results = await asyncio.gather(
            *(self._cancel_and_stop_chat_agent(agent) for agent in agents),
            return_exceptions=True,
        )
        if session_quiesce_events:
            await asyncio.gather(*(event.wait() for event in session_quiesce_events))
        async with self._chat_clear_lock:
            extra_keys = [
                key
                for key in self._agents
                if self._parse_agent_key(key)[0] == TaskAgentType.CHAT.value
            ]
            extra_agents = [self._agents.pop(key) for key in extra_keys]
            for key in extra_keys:
                self._instance_metadata.pop(key, None)
        extra_results = await asyncio.gather(
            *(self._cancel_and_stop_chat_agent(agent) for agent in extra_agents),
            return_exceptions=True,
        )
        failures = [
            result
            for result in (*initial_results, *extra_results)
            if isinstance(result, BaseException)
        ]
        if failures:
            raise RuntimeError(
                f"Failed to stop {len(failures)} chat agent(s) before memory clear"
            ) from failures[0]

    @staticmethod
    async def _cancel_and_stop_chat_agent(
        agent: TaskAgent,
        *,
        reason: str = "memory_clear",
        anchor_turn_id: str | None = None,
    ) -> None:
        cancel_handler = getattr(agent, "request_session_cancel", None)
        cancel_failure: BaseException | None = None
        if callable(cancel_handler):
            try:
                await cancel_handler(
                    session_id=agent.agent_id,
                    requested_by="system",
                    reason=reason,
                    anchor_turn_id=anchor_turn_id,
                )
            except BaseException as exc:
                cancel_failure = exc
                logger.exception(
                    "Failed to request chat run cancellation before destructive cleanup | key=%s",
                    agent.runtime_key,
                )
        cancel_postprocess = getattr(
            agent,
            "cancel_postprocess_for_destructive_change",
            None,
        )
        if callable(cancel_postprocess):
            try:
                await cancel_postprocess()
            except BaseException as exc:
                if cancel_failure is None:
                    cancel_failure = exc
                logger.exception(
                    "Failed to cancel chat post-processing before destructive cleanup | key=%s",
                    agent.runtime_key,
                )
        try:
            await agent.stop()
        except BaseException as stop_failure:
            if cancel_failure is not None:
                logger.error(
                    "Chat cancellation and stop both failed before destructive cleanup | key=%s",
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
                "Failed to cancel chat run before destructive cleanup"
            ) from cancel_failure

    async def cancel_chat_session_work(
        self,
        *,
        session_id: str,
        turn_id: str | None = None,
        expected_run_id: str | None = None,
        expected_run_revision: int | None = None,
        require_run_match: bool = False,
        match_turn_scope: bool = False,
    ) -> bool:
        """Stop any session run that may have consumed a deleted user turn."""
        return await self._chat_message_delete.cancel_session_work(
            session_id=session_id,
            turn_id=turn_id,
            expected_run_id=expected_run_id,
            expected_run_revision=expected_run_revision,
            require_run_match=require_run_match,
            match_turn_scope=match_turn_scope,
        )

    @asynccontextmanager
    async def hold_chat_session_for_message_delete(
        self,
        *,
        session_id: str,
        turn_id: str,
        expected_run_id: str | None,
        expected_run_revision: int,
        match_turn_scope: bool,
    ) -> AsyncIterator[ChatMessageDeleteHold]:
        """Hold one session while an exact message deletion is finalized."""

        async with self._chat_message_delete.hold_session_for_message_delete(
            session_id=session_id,
            turn_id=turn_id,
            expected_run_id=expected_run_id,
            expected_run_revision=expected_run_revision,
            match_turn_scope=match_turn_scope,
        ) as hold:
            yield hold

    async def ensure_agent(self, agent_type: TaskAgentType | str, agent_id: str) -> TaskAgent:
        if get_task_agent_type_value(agent_type) == TaskAgentType.CHAT.value:
            normalized_agent_id = str(agent_id)
            while True:
                await self._chat_work_resumed.wait()
                session_quiesce = self._chat_session_quiesce_events.get(
                    normalized_agent_id
                )
                if session_quiesce is not None:
                    await session_quiesce.wait()
                    continue
                async with self._chat_clear_lock:
                    if (
                        self._chat_pause_depth == 0
                        and normalized_agent_id
                        not in self._chat_session_quiesce_events
                    ):
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

    async def add_fact_to_agent(
        self, agent_type: TaskAgentType | str, agent_id: str, fact: FactRecord
    ) -> bool:
        """Add fact to agent, returns True if successful, False if rejected."""
        try:
            if get_task_agent_type_value(agent_type) == TaskAgentType.CHAT.value:
                normalized_agent_id = str(agent_id)
                while True:
                    await self._chat_work_resumed.wait()
                    session_quiesce = self._chat_session_quiesce_events.get(
                        normalized_agent_id
                    )
                    if session_quiesce is not None:
                        await session_quiesce.wait()
                        continue
                    async with self._chat_clear_lock:
                        if self._chat_pause_depth != 0:
                            continue
                        if (
                            normalized_agent_id
                            in self._chat_session_quiesce_events
                        ):
                            continue
                        if await self._is_blocked_user_message(fact):
                            self._blocked_user_message_rejected_count += 1
                            logger.info(
                                "Rejected user-message fact for a deleted chat scope",
                                session_id=str(fact.payload.get("session_id") or ""),
                                turn_id=str(fact.payload.get("turn_id") or ""),
                            )
                            return False
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
                        delivery_identity = self._user_message_delivery_identity(fact)
                        if delivery_identity is None:
                            result = await agent.add_fact(fact)
                        else:
                            if (
                                self._user_message_delivery_admitter is None
                                or self._runtime_command_acknowledger is None
                            ):
                                raise RuntimeError(
                                    "Managed user-message delivery callbacks are not configured"
                                )
                            admission = await agent.add_fact_with_admission(
                                fact,
                                admit=lambda: self._user_message_delivery_admitter(
                                    turn_id=delivery_identity.turn_id,
                                    delivery_attempt_no=(
                                        delivery_identity.delivery_attempt_no
                                    ),
                                    command_id=delivery_identity.runtime_command_id,
                                    updated_at_ms=int(time.time() * 1000),
                                ),
                            )
                            if admission.superseded:
                                self._superseded_user_message_count += 1
                            if admission.queued or admission.superseded:
                                await self._runtime_command_acknowledger(
                                    delivery_identity.runtime_command_id
                                )
                            result = admission.queued or admission.superseded
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
            "blocked_user_message_rejected_count": self._blocked_user_message_rejected_count,
            "superseded_user_message_count": self._superseded_user_message_count,
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

    async def _is_blocked_user_message(self, fact: FactRecord) -> bool:
        if fact.event_type != EventTypes.USER_MESSAGE:
            return False
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        user_id = str(payload.get("user_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip()
        if self._user_message_scope_blocker is None:
            return False
        return await self._user_message_scope_blocker(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id or None,
            correlation_id=fact.correlation_id,
        )

    @staticmethod
    def _user_message_delivery_identity(
        fact: FactRecord,
    ) -> _UserMessageDeliveryIdentity | None:
        if fact.event_type != EventTypes.USER_MESSAGE:
            return None
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        raw_attempt_no = fact.delivery_attempt_no
        raw_command_id = fact.runtime_command_id
        if raw_attempt_no is None and raw_command_id is None:
            return None
        turn_id = str(payload.get("turn_id") or "").strip()
        if not turn_id or raw_attempt_no is None or raw_command_id is None:
            raise ValueError(
                "Managed user message requires turn, attempt, and command identity"
            )
        if isinstance(raw_attempt_no, bool) or isinstance(raw_command_id, bool):
            raise ValueError("Managed user-message delivery identity is invalid")
        try:
            delivery_attempt_no = int(raw_attempt_no)
            runtime_command_id = int(raw_command_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Managed user-message delivery identity is invalid"
            ) from exc
        if delivery_attempt_no < 0 or runtime_command_id <= 0:
            raise ValueError("Managed user-message delivery identity is invalid")
        return _UserMessageDeliveryIdentity(
            turn_id=turn_id,
            delivery_attempt_no=delivery_attempt_no,
            runtime_command_id=runtime_command_id,
        )

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
            if (
                get_task_agent_type_value(core_type) == get_task_agent_type_value(agent_type)
                and core_id == agent_id
            ):
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
            is_busy = agent.has_inflight_work() if agent else False

            if idle_time > self._idle_ttl_seconds and not is_busy:
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
            is_busy = agent.has_inflight_work() if agent else False

            if not is_busy and meta.last_active_at < oldest_time:
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
