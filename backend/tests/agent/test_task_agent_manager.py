import asyncio

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover

    class _Mark:
        @staticmethod
        def asyncio(func):
            return func

    class _PytestFallback:
        mark = _Mark()

    pytest = _PytestFallback()

from magi.agent.runtime import TaskAgent, TaskAgentManager, TaskAgentType
from magi.agent.task_agents import DefaultTaskAgent
from magi.agent.runtime.contracts import FactRecord
from magi.awareness.contracts import SensorEvent
from magi.events.events import EventTypes


class _CollectTaskAgent(TaskAgent):
    def __init__(self, agent_type: TaskAgentType, agent_id: str):
        super().__init__(agent_type=agent_type, agent_id=agent_id)
        self.collected = []

    async def handle_fact(self, fact: FactRecord) -> None:
        self.collected.append(fact)


@pytest.mark.asyncio
async def test_task_agent_manager_hybrid_creation_and_dispatch():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
    )
    await manager.start_all(event_emitter=None)

    # Core instances should exist.
    assert manager.get_agent(TaskAgentType.CHAT, "default") is not None

    # Dynamic instance should be created on demand.
    fact = FactRecord(
        agent_id="chat:u-chat",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="u-chat",
        event_type="USER_MESSAGE",
        payload={"content": "hello"},
    )
    await manager.add_fact_to_agent(TaskAgentType.CHAT, "u-chat", fact)
    await asyncio.sleep(0.2)

    dynamic = manager.get_agent(TaskAgentType.CHAT, "u-chat")
    assert dynamic is not None
    assert dynamic.get_stats()["processed"] >= 1

    await manager.stop_all()


def test_task_agent_manager_routes_user_messages_by_session_id():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
    )

    targets = manager.resolve_targets(
        SensorEvent(
            sensor_name="user_input_sensor",
            event_type=EventTypes.USER_MESSAGE,
            payload={
                "content": "hello",
                "user_id": "u-chat",
                "session_id": "s-chat",
            },
        )
    )

    assert targets == [(TaskAgentType.CHAT, "s-chat")]


def test_task_agent_manager_rejects_user_messages_without_session_id():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
    )

    with pytest.raises(ValueError, match="session_id"):
        manager.resolve_targets(
            SensorEvent(
                sensor_name="user_input_sensor",
                event_type=EventTypes.USER_MESSAGE,
                payload={
                    "content": "hello",
                    "user_id": "u-chat",
                },
            )
        )


@pytest.mark.asyncio
async def test_task_agent_manager_supports_default_agent_type():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
        create_default_agent=lambda agent_type, agent_id: DefaultTaskAgent(agent_type, agent_id),
    )
    await manager.start_all(event_emitter=None)

    fact = FactRecord(
        agent_id="analytics:tenant-a",
        agent_type="analytics",
        agent_instance_id="tenant-a",
        event_type="ANALYTICS_EVENT",
        payload={"target_task_agent_type": "analytics", "target_task_agent_id": "tenant-a"},
    )
    await manager.add_fact_to_agent("analytics", "tenant-a", fact)
    await asyncio.sleep(0.1)

    assert manager.get_agent("analytics", "tenant-a") is not None
    await manager.stop_all()


def _user_fact(session_id: str) -> FactRecord:
    return FactRecord(
        agent_id=f"chat:{session_id}",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id=session_id,
        event_type="USER_MESSAGE",
        payload={"content": "hi"},
    )


@pytest.mark.asyncio
async def test_evicts_oldest_idle_instance_instead_of_silently_rejecting():
    """At capacity with an idle instance available, a new session must reclaim
    the oldest idle slot rather than being silently dropped (regression for the
    no-op _maybe_evict_idle_instances bug)."""
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
        max_dynamic_instances=2,
    )
    await manager.start_all(event_emitter=None)

    # Two idle dynamic instances fill capacity (empty fact queues).
    await manager.ensure_agent(TaskAgentType.CHAT, "s-old")
    await asyncio.sleep(0.01)  # make s-old strictly older than s-new
    await manager.ensure_agent(TaskAgentType.CHAT, "s-new")

    # Third session arrives at capacity. The oldest idle instance must be
    # recycled so the new session is accepted — not silently dropped.
    accepted = await manager.add_fact_to_agent(TaskAgentType.CHAT, "s-third", _user_fact("s-third"))

    assert accepted is True
    assert manager.get_agent(TaskAgentType.CHAT, "s-third") is not None
    assert manager.get_agent(TaskAgentType.CHAT, "s-old") is None
    assert manager.get_agent(TaskAgentType.CHAT, "s-new") is not None

    await manager.stop_all()


class _NeverConsumeTaskAgent(TaskAgent):
    """TaskAgent that never drains its queue — simulates a permanently busy instance."""

    async def start(self, *args, **kwargs) -> None:
        pass  # intentionally do not spawn the consume loop

    async def stop(self) -> None:
        pass


@pytest.mark.asyncio
async def test_does_not_evict_busy_instance_and_rejects_explicitly_when_full():
    """At capacity with no idle instance to reclaim, a new session is rejected
    explicitly (observable via return value + counter) and the busy instance is
    not evicted."""
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NeverConsumeTaskAgent(
            agent_type=TaskAgentType.CHAT, agent_id=agent_id
        ),
        max_dynamic_instances=1,
    )
    await manager.start_all(event_emitter=None)

    # Occupy the only dynamic slot with a BUSY instance (non-empty queue).
    busy = await manager.ensure_agent(TaskAgentType.CHAT, "busy")
    busy._fact_queue.put_nowait(_user_fact("busy"))
    assert busy._fact_queue.qsize() == 1

    # New session at capacity with nothing idle to reclaim: must be rejected
    # explicitly, and the busy instance must survive.
    accepted = await manager.add_fact_to_agent(
        TaskAgentType.CHAT, "overflow", _user_fact("overflow")
    )

    assert accepted is False
    assert manager.get_agent(TaskAgentType.CHAT, "overflow") is None
    assert manager.get_agent(TaskAgentType.CHAT, "busy") is not None
    assert manager.get_stats()["enqueue_rejected_count"] >= 1

    await manager.stop_all()


class _BlockedResponseAgent(TaskAgent):
    def __init__(
        self,
        agent_id: str,
        *,
        response_gate: asyncio.Event,
        response_started: asyncio.Event,
        chat_rows: list[str],
        memory_rows: list[str],
    ) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        self._response_gate = response_gate
        self._response_started = response_started
        self._chat_rows = chat_rows
        self._memory_rows = memory_rows

    async def call_llm(self, context, llm_params):
        self._response_started.set()
        await self._response_gate.wait()
        return context

    async def parse_result(self, context, raw_result) -> None:
        content = str(context.latest_fact.payload.get("content") or "")
        self._chat_rows.append(content)
        self._memory_rows.append(content)


@pytest.mark.asyncio
async def test_memory_clear_pause_cancels_old_chat_work_and_admits_new_work_after_resume():
    response_gate = asyncio.Event()
    response_started = asyncio.Event()
    chat_rows: list[str] = []
    memory_rows: list[str] = []

    def create_agent(agent_id: str) -> _BlockedResponseAgent:
        return _BlockedResponseAgent(
            agent_id,
            response_gate=response_gate,
            response_started=response_started,
            chat_rows=chat_rows,
            memory_rows=memory_rows,
        )

    manager = TaskAgentManager(create_chat_agent=create_agent)
    await manager.start_all(event_emitter=None)
    before = FactRecord(
        agent_id="chat:session-clear",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="session-clear",
        event_type=EventTypes.USER_MESSAGE,
        payload={"content": "before clear"},
    )
    queued = FactRecord(
        agent_id="chat:session-clear",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="session-clear",
        event_type=EventTypes.USER_MESSAGE,
        payload={"content": "queued before clear"},
    )
    assert await manager.add_fact_to_agent(TaskAgentType.CHAT, "session-clear", before)
    await asyncio.wait_for(response_started.wait(), timeout=1)
    assert await manager.add_fact_to_agent(TaskAgentType.CHAT, "session-clear", queued)

    cancelled_count = await manager.pause_chat_work_and_cancel_all()
    assert cancelled_count == 2
    chat_rows.clear()
    memory_rows.clear()
    response_gate.set()

    after = FactRecord(
        agent_id="chat:session-clear",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="session-clear",
        event_type=EventTypes.USER_MESSAGE,
        payload={"content": "after clear"},
    )
    after_task = asyncio.create_task(
        manager.add_fact_to_agent(TaskAgentType.CHAT, "session-clear", after)
    )
    await asyncio.sleep(0)
    assert not after_task.done()

    await manager.resume_chat_work()
    assert await asyncio.wait_for(after_task, timeout=1) is True
    for _ in range(50):
        if chat_rows:
            break
        await asyncio.sleep(0.01)

    assert chat_rows == ["after clear"]
    assert memory_rows == ["after clear"]
    await manager.stop_all()


@pytest.mark.asyncio
async def test_deleted_chat_scope_stops_active_work_and_rejects_replayed_turn():
    response_gate = asyncio.Event()
    response_started = asyncio.Event()
    chat_rows: list[str] = []
    memory_rows: list[str] = []
    blocked_turns = {("session-delete", "turn-delete")}

    async def is_blocked(**scope) -> bool:  # type: ignore[no-untyped-def]
        return (str(scope["session_id"]), str(scope.get("turn_id") or "")) in blocked_turns

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _BlockedResponseAgent(
            agent_id,
            response_gate=response_gate,
            response_started=response_started,
            chat_rows=chat_rows,
            memory_rows=memory_rows,
        ),
        user_message_scope_blocker=is_blocked,
    )
    await manager.start_all(event_emitter=None)
    active_fact = FactRecord(
        agent_id="chat:session-delete",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="session-delete",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "user-1",
            "session_id": "session-delete",
            "turn_id": "turn-active",
            "content": "private active work",
        },
    )
    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "session-delete",
        active_fact,
    )
    await asyncio.wait_for(response_started.wait(), timeout=1)

    assert await manager.cancel_chat_session_work(
        session_id="session-delete",
        turn_id="turn-delete",
    )
    response_gate.set()
    await asyncio.sleep(0)
    assert manager.get_agent(TaskAgentType.CHAT, "session-delete") is None
    assert chat_rows == []
    assert memory_rows == []

    replayed = FactRecord(
        agent_id="chat:session-delete",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="session-delete",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "user-1",
            "session_id": "session-delete",
            "turn_id": "turn-delete",
            "content": "must stay blocked",
        },
    )
    assert not await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "session-delete",
        replayed,
    )
    assert manager.get_stats()["blocked_user_message_rejected_count"] == 1
    await manager.stop_all()


@pytest.mark.asyncio
async def test_memory_clear_resume_can_retry_default_agent_after_start_failure():
    start_attempts = 0

    class FailsOnceAgent(_CollectTaskAgent):
        async def start(self, *args, **kwargs) -> None:
            nonlocal start_attempts
            start_attempts += 1
            if start_attempts == 2:
                raise RuntimeError("restart failed")
            await super().start(*args, **kwargs)

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: FailsOnceAgent(
            TaskAgentType.CHAT,
            agent_id,
        )
    )
    await manager.start_all(event_emitter=None)
    await manager.pause_chat_work_and_cancel_all()

    with pytest.raises(RuntimeError, match="restart failed"):
        await manager.resume_chat_work()

    assert manager.get_agent(TaskAgentType.CHAT, "default") is None
    recovered = await manager.ensure_agent(TaskAgentType.CHAT, "default")
    assert recovered is manager.get_agent(TaskAgentType.CHAT, "default")
    assert start_attempts == 3
    await manager.stop_all()


@pytest.mark.asyncio
async def test_chat_admission_recovers_after_quiesce_failure():
    creation_count = 0

    class StopFailsOnceAgent(_CollectTaskAgent):
        def __init__(self, agent_id: str, *, fail_stop: bool) -> None:
            super().__init__(TaskAgentType.CHAT, agent_id)
            self._fail_stop = fail_stop

        async def stop(self) -> None:
            await super().stop()
            if self._fail_stop:
                self._fail_stop = False
                raise RuntimeError("stop failed")

    def create_agent(agent_id: str) -> StopFailsOnceAgent:
        nonlocal creation_count
        creation_count += 1
        return StopFailsOnceAgent(agent_id, fail_stop=creation_count == 1)

    manager = TaskAgentManager(create_chat_agent=create_agent)
    await manager.start_all(event_emitter=None)

    with pytest.raises(RuntimeError, match="Failed to stop 1 chat agent"):
        await manager.pause_chat_work_and_cancel_all()

    await manager.resume_chat_work()
    accepted = await asyncio.wait_for(
        manager.add_fact_to_agent(
            TaskAgentType.CHAT,
            "after-failed-clear",
            _user_fact("after-failed-clear"),
        ),
        timeout=1,
    )

    assert accepted is True
    assert manager.get_agent(TaskAgentType.CHAT, "default") is not None
    assert manager.get_agent(TaskAgentType.CHAT, "after-failed-clear") is not None
    await manager.stop_all()


@pytest.mark.asyncio
async def test_sensor_fact_waiting_at_clear_boundary_is_rejected_after_generation_changes():
    generation = 0
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(
            TaskAgentType.CHAT,
            agent_id,
        ),
        user_message_generation_getter=lambda: generation,
    )
    await manager.start_all(event_emitter=None)
    await manager.pause_chat_work_and_cancel_all()

    stale_fact = FactRecord(
        agent_id="chat:stale-session",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="stale-session",
        event_type=EventTypes.USER_MESSAGE,
        payload={"session_id": "stale-session", "content": "old queued message"},
        user_message_generation=0,
    )
    waiting_add = asyncio.create_task(
        manager.add_fact_to_agent(TaskAgentType.CHAT, "stale-session", stale_fact)
    )
    await asyncio.sleep(0)
    assert not waiting_add.done()

    generation = 1
    await manager.resume_chat_work()

    assert await asyncio.wait_for(waiting_add, timeout=1) is False
    assert manager.get_agent(TaskAgentType.CHAT, "stale-session") is None
    assert manager.get_stats()["stale_user_message_rejected_count"] == 1
    await manager.stop_all()


@pytest.mark.asyncio
async def test_router_fact_without_generation_is_fail_closed_when_generation_is_active():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(
            TaskAgentType.CHAT,
            agent_id,
        ),
        user_message_generation_getter=lambda: 1,
    )
    await manager.start_all(event_emitter=None)
    router_fact_missing_generation = FactRecord(
        agent_id="chat:legacy-session",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="legacy-session",
        event_type=EventTypes.USER_MESSAGE,
        payload={"session_id": "legacy-session", "content": "legacy queued message"},
        user_message_generation=None,
    )

    accepted = await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "legacy-session",
        router_fact_missing_generation,
    )

    assert accepted is False
    assert manager.get_agent(TaskAgentType.CHAT, "legacy-session") is None
    assert manager.get_stats()["stale_user_message_rejected_count"] == 1
    await manager.stop_all()


@pytest.mark.asyncio
async def test_reinjected_fact_uses_current_generation_and_old_reinject_is_rejected():
    generation = 3
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(
            TaskAgentType.CHAT,
            agent_id,
        ),
        user_message_generation_getter=lambda: generation,
    )
    await manager.start_all(event_emitter=None)
    current_reinject = FactRecord(
        agent_id="chat:reinject-session",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="reinject-session",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "session_id": "reinject-session",
            "content": "deferred turn",
            "metadata": {"reinjected_from": "deferred_pending_turn"},
        },
        user_message_generation=manager.current_user_message_generation(),
    )

    assert (
        await manager.add_fact_to_agent(
            TaskAgentType.CHAT,
            "reinject-session",
            current_reinject,
        )
        is True
    )

    generation = 4
    assert (
        await manager.add_fact_to_agent(
            TaskAgentType.CHAT,
            "reinject-session",
            current_reinject,
        )
        is False
    )
    assert manager.get_stats()["stale_user_message_rejected_count"] == 1
    await manager.stop_all()
