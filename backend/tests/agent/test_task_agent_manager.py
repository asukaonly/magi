import asyncio
from types import SimpleNamespace

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
from magi.chat import ChatStore
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
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


@pytest.mark.asyncio
async def test_does_not_evict_instance_while_response_is_in_progress():
    response_started = asyncio.Event()
    release_response = asyncio.Event()
    completed: list[str] = []

    class _ActiveResponseAgent(TaskAgent):
        async def call_llm(self, context, llm_params):  # type: ignore[no-untyped-def]
            response_started.set()
            await release_response.wait()
            return context

        async def parse_result(self, context, raw_result) -> None:  # type: ignore[no-untyped-def]
            completed.append(str(context.latest_fact.payload.get("content") or ""))

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _ActiveResponseAgent(
            agent_type=TaskAgentType.CHAT,
            agent_id=agent_id,
        ),
        max_dynamic_instances=1,
    )
    await manager.start_all(event_emitter=None)

    try:
        accepted = await manager.add_fact_to_agent(
            TaskAgentType.CHAT,
            "active",
            _user_fact("active"),
        )
        assert accepted is True
        await asyncio.wait_for(response_started.wait(), timeout=1)

        active_agent = manager.get_agent(TaskAgentType.CHAT, "active")
        assert active_agent is not None
        assert active_agent._fact_queue.empty()
        assert active_agent.has_inflight_work() is True

        manager._idle_ttl_seconds = 0
        manager._instance_metadata[active_agent.runtime_key].last_active_at = 0
        await manager._cleanup_idle_instances()
        assert manager.get_agent(TaskAgentType.CHAT, "active") is active_agent

        overflow_accepted = await manager.add_fact_to_agent(
            TaskAgentType.CHAT,
            "overflow",
            _user_fact("overflow"),
        )

        assert overflow_accepted is False
        assert manager.get_agent(TaskAgentType.CHAT, "active") is active_agent
        assert manager.get_agent(TaskAgentType.CHAT, "overflow") is None

        release_response.set()
        for _ in range(20):
            if completed:
                break
            await asyncio.sleep(0.01)
        assert completed == ["hi"]
    finally:
        release_response.set()
        await manager.stop_all()


@pytest.mark.asyncio
async def test_does_not_evict_agent_during_durable_admission() -> None:
    admission_started = asyncio.Event()
    release_admission = asyncio.Event()
    acknowledged: list[int] = []

    async def admit(**_identity) -> bool:  # type: ignore[no-untyped-def]
        admission_started.set()
        await release_admission.wait()
        return True

    async def acknowledge(command_id: int) -> None:
        acknowledged.append(command_id)

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NeverConsumeTaskAgent(
            agent_type=TaskAgentType.CHAT,
            agent_id=agent_id,
        ),
        idle_ttl_seconds=0,
        user_message_delivery_admitter=admit,
        runtime_command_acknowledger=acknowledge,
    )
    await manager.start_all(event_emitter=None)
    fact = FactRecord(
        agent_id="chat:admission-race",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="admission-race",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "user-1",
            "session_id": "admission-race",
            "turn_id": "turn-admission-race",
            "content": "hello",
        },
        delivery_attempt_no=0,
        runtime_command_id=909,
    )

    admission = asyncio.create_task(
        manager.add_fact_to_agent(
            TaskAgentType.CHAT,
            "admission-race",
            fact,
        )
    )
    try:
        await asyncio.wait_for(admission_started.wait(), timeout=1)
        agent = manager.get_agent(TaskAgentType.CHAT, "admission-race")
        assert agent is not None
        assert agent.has_inflight_work() is True
        manager._instance_metadata[agent.runtime_key].last_active_at = 0
        await manager._cleanup_idle_instances()
        assert manager.get_agent(TaskAgentType.CHAT, "admission-race") is agent

        release_admission.set()
        assert await asyncio.wait_for(admission, timeout=1) is True
        assert agent._fact_queue.qsize() == 1
        assert acknowledged == [909]
    finally:
        release_admission.set()
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
        started_rows: list[str] | None = None,
    ) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        self._response_gate = response_gate
        self._response_started = response_started
        self._chat_rows = chat_rows
        self._memory_rows = memory_rows
        self._started_rows = started_rows
        self.active_run_id = "run-active"
        self.active_run_revision = 2
        self.active_turn_id = "turn-active"

    def matches_active_session_run(
        self,
        *,
        session_id: str,
        turn_id: str | None,
        run_id: str | None,
        run_revision: int | None,
        match_turn_scope: bool,
    ) -> bool:
        if session_id != self.agent_id:
            return False
        if run_id is not None and run_revision is not None:
            return bool(
                run_id == self.active_run_id
                and run_revision == self.active_run_revision
            )
        return match_turn_scope and turn_id == self.active_turn_id

    async def call_llm(self, context, llm_params):
        if self._started_rows is not None:
            self._started_rows.append(
                str(context.latest_fact.payload.get("content") or "")
            )
        self._response_started.set()
        await self._response_gate.wait()
        return context

    async def parse_result(self, context, raw_result) -> None:
        content = str(context.latest_fact.payload.get("content") or "")
        self._chat_rows.append(content)
        self._memory_rows.append(content)


def test_active_session_run_match_falls_back_to_exact_turn_identity():
    from magi.chat.task_agent.session_control import ChatSessionControlMixin

    active_run = SimpleNamespace(
        run_id="run-active",
        revision=2,
        root_turn_id="turn-root",
        pending_turns=[SimpleNamespace(turn_id="turn-pending")],
    )
    host = SimpleNamespace(
        _session_run_coordinator=SimpleNamespace(
            get_active_run=lambda session_id: (
                active_run if session_id == "session-active" else None
            )
        ),
        snapshot_inflight_facts=lambda: (),
    )

    assert ChatSessionControlMixin.matches_active_session_run(
        host,
        session_id="session-active",
        turn_id="turn-root",
        run_id=None,
        run_revision=0,
        match_turn_scope=True,
    )
    assert ChatSessionControlMixin.matches_active_session_run(
        host,
        session_id="session-active",
        turn_id="turn-pending",
        run_id=None,
        run_revision=0,
        match_turn_scope=True,
    )
    assert not ChatSessionControlMixin.matches_active_session_run(
        host,
        session_id="session-active",
        turn_id="turn-old",
        run_id=None,
        run_revision=0,
        match_turn_scope=True,
    )
    assert not ChatSessionControlMixin.matches_active_session_run(
        host,
        session_id="session-active",
        turn_id="turn-root",
        run_id="run-old",
        run_revision=1,
        match_turn_scope=False,
    )
    assert ChatSessionControlMixin.matches_active_session_run(
        host,
        session_id="session-active",
        turn_id="turn-root",
        run_id="run-old",
        run_revision=1,
        match_turn_scope=True,
    )
    assert ChatSessionControlMixin.matches_active_session_run(
        host,
        session_id="session-active",
        turn_id="turn-consumed-follow-up",
        run_id="run-active",
        run_revision=1,
        match_turn_scope=True,
    )
    assert not ChatSessionControlMixin.matches_active_session_run(
        host,
        session_id="session-active",
        turn_id="turn-consumed-follow-up",
        run_id="run-active",
        run_revision=1,
        match_turn_scope=False,
    )


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
    delete_started = False

    async def is_blocked(**scope) -> bool:  # type: ignore[no-untyped-def]
        return delete_started and (
            str(scope["session_id"]),
            str(scope.get("turn_id") or ""),
        ) in blocked_turns

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

    delete_started = True
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
async def test_old_message_delete_does_not_cancel_a_newer_active_run():
    response_gate = asyncio.Event()
    response_started = asyncio.Event()
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _BlockedResponseAgent(
            agent_id,
            response_gate=response_gate,
            response_started=response_started,
            chat_rows=[],
            memory_rows=[],
        )
    )
    await manager.start_all(event_emitter=None)
    fact = FactRecord(
        agent_id="chat:session-new-run",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="session-new-run",
        event_type=EventTypes.USER_MESSAGE,
        payload={"session_id": "session-new-run", "content": "new run"},
    )
    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "session-new-run",
        fact,
    )
    await asyncio.wait_for(response_started.wait(), timeout=1)

    assert not await manager.cancel_chat_session_work(
        session_id="session-new-run",
        turn_id="turn-old",
        expected_run_id="run-old",
        expected_run_revision=1,
        require_run_match=True,
        match_turn_scope=False,
    )
    assert manager.get_agent(TaskAgentType.CHAT, "session-new-run") is not None

    assert not await manager.cancel_chat_session_work(
        session_id="session-new-run",
        turn_id="turn-old",
        require_run_match=True,
        match_turn_scope=True,
    )
    assert manager.get_agent(TaskAgentType.CHAT, "session-new-run") is not None

    assert await manager.cancel_chat_session_work(
        session_id="session-new-run",
        turn_id="turn-active",
        require_run_match=True,
        match_turn_scope=True,
    )
    response_gate.set()
    assert manager.get_agent(TaskAgentType.CHAT, "session-new-run") is None
    await manager.stop_all()


@pytest.mark.asyncio
async def test_failed_stop_restores_agent_and_queued_follow_up_once() -> None:
    active_started = asyncio.Event()
    active_gate = asyncio.Event()
    parsed_rows: list[str] = []

    class _StopFailsBeforeCancelAgent(TaskAgent):
        def __init__(self, agent_id: str) -> None:
            super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
            self._fail_stop = agent_id == "stop-failure"

        async def stop(self) -> None:
            if self._fail_stop:
                self._fail_stop = False
                raise RuntimeError("stop failed before cancellation")
            await super().stop()

        async def call_llm(self, context, llm_params):  # type: ignore[no-untyped-def]
            if str(context.latest_fact.payload.get("content") or "") == "active":
                active_started.set()
                await active_gate.wait()
            return llm_params

        async def parse_result(self, context, raw_result) -> None:  # type: ignore[no-untyped-def]
            parsed_rows.append(str(context.latest_fact.payload.get("content") or ""))

    def fact(turn_id: str, content: str) -> FactRecord:
        return FactRecord(
            agent_id="chat:stop-failure",
            agent_type=TaskAgentType.CHAT.value,
            agent_instance_id="stop-failure",
            event_type=EventTypes.USER_MESSAGE,
            payload={
                "user_id": "user-1",
                "session_id": "stop-failure",
                "turn_id": turn_id,
                "content": content,
            },
        )

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _StopFailsBeforeCancelAgent(agent_id),
        user_message_scope_blocker=lambda **_scope: asyncio.sleep(0, result=False),
    )
    await manager.start_all(event_emitter=None)
    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "stop-failure",
        fact("turn-active", "active"),
    )
    await asyncio.wait_for(active_started.wait(), timeout=1)
    original = manager.get_agent(TaskAgentType.CHAT, "stop-failure")
    assert original is not None
    assert await original.add_fact(fact("turn-follow-up", "follow-up"))

    with pytest.raises(RuntimeError, match="stop failed before cancellation"):
        await manager.cancel_chat_session_work(
            session_id="stop-failure",
            turn_id="turn-active",
        )
    assert manager.get_agent(TaskAgentType.CHAT, "stop-failure") is original
    assert "stop-failure" not in manager._chat_session_quiesce_events

    active_gate.set()
    for _ in range(100):
        if parsed_rows == ["active", "follow-up"]:
            break
        await asyncio.sleep(0.01)
    assert parsed_rows == ["active", "follow-up"]
    await manager.stop_all()


@pytest.mark.asyncio
async def test_privacy_delete_does_not_restart_batch_completed_before_stop() -> None:
    processing_started = asyncio.Event()
    release_processing = asyncio.Event()
    cancellation_started = asyncio.Event()
    release_cancellation = asyncio.Event()
    completed = asyncio.Event()
    parsed_rows: list[str] = []
    session_generations: dict[str, int] = {}

    class _CompletionWindowAgent(TaskAgent):
        def __init__(self, agent_id: str) -> None:
            super().__init__(TaskAgentType.CHAT, agent_id)
            self._saved_start: tuple[object, object, object] | None = None

        async def start(  # type: ignore[no-untyped-def]
            self,
            event_emitter,
            task_agent_manager=None,
            sensor_hub=None,
        ) -> None:
            self._saved_start = (
                event_emitter,
                task_agent_manager,
                sensor_hub,
            )

        async def begin_processing(self) -> None:
            assert self._saved_start is not None
            await TaskAgent.start(self, *self._saved_start)

        async def call_llm(self, context, llm_params):  # type: ignore[no-untyped-def]
            processing_started.set()
            await release_processing.wait()
            return llm_params

        async def parse_result(self, context, raw_result) -> None:  # type: ignore[no-untyped-def]
            parsed_rows.append(
                str(context.latest_fact.payload.get("content") or "")
            )
            completed.set()

        async def request_session_cancel(self, **_kwargs):  # type: ignore[no-untyped-def]
            cancellation_started.set()
            await release_cancellation.wait()
            return None

    class _UnexpectedReplacementAgent(TaskAgent):
        async def parse_result(self, context, raw_result) -> None:  # type: ignore[no-untyped-def]
            parsed_rows.append(
                f"restarted:{context.latest_fact.payload.get('content') or ''}"
            )

    def create_agent(agent_id: str) -> TaskAgent:
        generation = session_generations.get(agent_id, 0) + 1
        session_generations[agent_id] = generation
        if agent_id == "completion-window" and generation == 1:
            return _CompletionWindowAgent(agent_id)
        return _UnexpectedReplacementAgent(TaskAgentType.CHAT, agent_id)

    async def is_blocked(**_scope) -> bool:  # type: ignore[no-untyped-def]
        return False

    def fact(turn_id: str, content: str) -> FactRecord:
        return FactRecord(
            agent_id="chat:completion-window",
            agent_type=TaskAgentType.CHAT.value,
            agent_instance_id="completion-window",
            event_type=EventTypes.USER_MESSAGE,
            payload={
                "user_id": "user-1",
                "session_id": "completion-window",
                "turn_id": turn_id,
                "content": content,
            },
        )

    manager = TaskAgentManager(
        create_chat_agent=create_agent,
        user_message_scope_blocker=is_blocked,
    )
    await manager.start_all(event_emitter=None)
    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "completion-window",
        fact("turn-delete", "delete target"),
    )
    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "completion-window",
        fact("turn-follow-up", "completed follow-up"),
    )
    old_agent = manager.get_agent(TaskAgentType.CHAT, "completion-window")
    assert isinstance(old_agent, _CompletionWindowAgent)
    await old_agent.begin_processing()
    await asyncio.wait_for(processing_started.wait(), timeout=1)

    cancellation = asyncio.create_task(
        manager.cancel_chat_session_work(
            session_id="completion-window",
            turn_id="turn-delete",
        )
    )
    await asyncio.wait_for(cancellation_started.wait(), timeout=1)
    release_processing.set()
    await asyncio.wait_for(completed.wait(), timeout=1)
    release_cancellation.set()

    assert await asyncio.wait_for(cancellation, timeout=1) is True
    await asyncio.sleep(0.02)
    assert parsed_rows == ["completed follow-up"]
    assert session_generations["completion-window"] == 1
    await manager.stop_all()


@pytest.mark.asyncio
async def test_cancelled_batch_is_not_counted_as_processed() -> None:
    started = asyncio.Event()
    gate = asyncio.Event()

    class _CancelledBatchAgent(TaskAgent):
        async def call_llm(self, context, llm_params):  # type: ignore[no-untyped-def]
            started.set()
            await gate.wait()
            return llm_params

    agent = _CancelledBatchAgent(TaskAgentType.CHAT, "processed-counter")
    await agent.start(event_emitter=None)
    assert await agent.add_fact(_user_fact("processed-counter"))
    await asyncio.wait_for(started.wait(), timeout=1)

    await agent.stop()

    assert agent.get_stats()["processed"] == 0


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


def _managed_user_fact(
    *,
    session_id: str,
    turn_id: str,
    delivery_attempt_no: int,
    runtime_command_id: int,
    content: str | None = None,
) -> FactRecord:
    return FactRecord(
        agent_id=f"chat:{session_id}",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id=session_id,
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "user-1",
            "session_id": session_id,
            "turn_id": turn_id,
            "content": content if content is not None else turn_id,
        },
        delivery_attempt_no=delivery_attempt_no,
        runtime_command_id=runtime_command_id,
    )


@pytest.mark.asyncio
async def test_managed_strict_interrupt_cancels_before_queue_drain(
    runtime_paths_with_schema,
) -> None:
    chat_store = ChatStore(
        db_path=str(runtime_paths_with_schema.chat_db_path)
    )
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="managed-interrupt",
        user_id="user-1",
        turn_id="turn-root",
        message_text="Inspect the login flow",
        created_at_ms=1710000000000,
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id="turn-root",
        delivery_attempt_no=0,
        command_id=801,
        updated_at_ms=1710000000001,
    )
    assert await chat_store.mark_user_turn_delivery_admitted(
        turn_id="turn-root",
        delivery_attempt_no=0,
        command_id=801,
        updated_at_ms=1710000000002,
    )
    await chat_store.create_user_turn(
        session_id="managed-interrupt",
        user_id="user-1",
        turn_id="turn-stop",
        message_text="Stop!",
        created_at_ms=1710000000010,
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id="turn-stop",
        delivery_attempt_no=0,
        command_id=802,
        updated_at_ms=1710000000011,
    )
    acknowledgements: list[int] = []

    class _NoDrainChatTaskAgent(ChatTaskAgent):
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            self.ingress_interrupt_checks = 0

        async def start(  # type: ignore[no-untyped-def]
            self,
            event_emitter,
            task_agent_manager=None,
            sensor_hub=None,
        ) -> None:
            self._event_emitter = event_emitter
            self._task_agent_manager = task_agent_manager
            self._sensor_hub = sensor_hub

        async def _request_ingress_interrupt_at_admission_boundary(
            self,
            fact: FactRecord,
        ) -> None:
            self.ingress_interrupt_checks += 1
            await super()._request_ingress_interrupt_at_admission_boundary(
                fact
            )

    async def admit(**identity) -> bool:  # type: ignore[no-untyped-def]
        return await chat_store.mark_user_turn_delivery_admitted(
            turn_id=identity["turn_id"],
            delivery_attempt_no=identity["delivery_attempt_no"],
            command_id=identity["command_id"],
            updated_at_ms=identity["updated_at_ms"],
        )

    async def acknowledge(command_id: int) -> None:
        acknowledgements.append(command_id)

    adapter = SimpleNamespace(
        model_name="fake-model",
        supports_embeddings=False,
    )
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NoDrainChatTaskAgent(
            agent_id=agent_id,
            llm_adapter=adapter,
            chat_store=chat_store,
        ),
        user_message_delivery_admitter=admit,
        runtime_command_acknowledger=acknowledge,
    )
    await manager.start_all(event_emitter=None)
    try:
        agent = await manager.ensure_agent(
            TaskAgentType.CHAT,
            "managed-interrupt",
        )
        assert isinstance(agent, _NoDrainChatTaskAgent)
        agent._session_run_coordinator._run_store.create_active_run(
            "managed-interrupt",
            root_turn_id="turn-root",
            root_user_message="Inspect the login flow",
            run_id="run-root",
        )

        assert await manager.add_fact_to_agent(
            TaskAgentType.CHAT,
            "managed-interrupt",
            _managed_user_fact(
                session_id="managed-interrupt",
                turn_id="turn-stop",
                delivery_attempt_no=0,
                runtime_command_id=802,
                content="Stop!",
            ),
        )

        active_run = agent._session_run_coordinator.get_active_run(
            "managed-interrupt"
        )
        root_turn = await chat_store.get_turn("turn-root")
        root_delivery = await chat_store.get_user_turn_delivery(
            turn_id="turn-root"
        )
        stop_delivery = await chat_store.get_user_turn_delivery(
            turn_id="turn-stop"
        )
        assert active_run is not None
        assert active_run.status == "cancelling"
        assert active_run.cancel_anchor_turn_id == "turn-stop"
        assert root_turn is not None
        assert root_turn.status == "cancelled"
        assert root_delivery is not None
        assert root_delivery.delivery_state == "terminal"
        assert stop_delivery is not None
        assert stop_delivery.delivery_state == "admitted"
        assert agent._fact_queue.qsize() == 1
        assert agent.ingress_interrupt_checks == 1
        assert acknowledgements == [802]
    finally:
        await manager.stop_all()
        await chat_store.shutdown()


@pytest.mark.asyncio
async def test_managed_user_message_is_admitted_once_and_duplicate_is_acked() -> None:
    state = {
        "turn_id": "turn-1",
        "attempt": 0,
        "command": None,
        "state": "ready",
    }
    acknowledgements: list[int] = []

    async def admit(**identity) -> bool:  # type: ignore[no-untyped-def]
        if (
            identity["turn_id"] == state["turn_id"]
            and identity["delivery_attempt_no"] == state["attempt"]
            and state["state"] in {"ready", "queued"}
            and (
                state["command"] is None
                or identity["command_id"] == state["command"]
            )
        ):
            state["state"] = "admitted"
            state["command"] = identity["command_id"]
            return True
        return False

    async def ack(command_id: int) -> None:
        acknowledgements.append(command_id)

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NeverConsumeTaskAgent(
            TaskAgentType.CHAT,
            agent_id,
        ),
        user_message_delivery_admitter=admit,
        runtime_command_acknowledger=ack,
    )
    await manager.start_all(event_emitter=None)
    fact = _managed_user_fact(
        session_id="managed-session",
        turn_id="turn-1",
        delivery_attempt_no=0,
        runtime_command_id=101,
    )

    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "managed-session",
        fact,
    )
    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "managed-session",
        fact,
    )

    agent = manager.get_agent(TaskAgentType.CHAT, "managed-session")
    assert agent is not None
    assert agent._fact_queue.qsize() == 1
    assert acknowledgements == [101, 101]
    assert manager.get_stats()["superseded_user_message_count"] == 1
    await manager.stop_all()


@pytest.mark.asyncio
async def test_old_delivery_attempt_is_acked_without_overwriting_current_attempt() -> None:
    state = {
        "turn_id": "turn-current",
        "attempt": 1,
        "command": None,
        "state": "ready",
    }
    acknowledgements: list[int] = []

    async def admit(**identity) -> bool:  # type: ignore[no-untyped-def]
        if (
            identity["turn_id"] == state["turn_id"]
            and identity["delivery_attempt_no"] == state["attempt"]
            and state["state"] == "ready"
            and state["command"] is None
        ):
            state["state"] = "admitted"
            state["command"] = identity["command_id"]
            return True
        return False

    async def ack(command_id: int) -> None:
        acknowledgements.append(command_id)

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NeverConsumeTaskAgent(
            TaskAgentType.CHAT,
            agent_id,
        ),
        user_message_delivery_admitter=admit,
        runtime_command_acknowledger=ack,
    )
    await manager.start_all(event_emitter=None)

    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "managed-session",
        _managed_user_fact(
            session_id="managed-session",
            turn_id="turn-current",
            delivery_attempt_no=0,
            runtime_command_id=101,
        ),
    )
    agent = manager.get_agent(TaskAgentType.CHAT, "managed-session")
    assert agent is not None and agent._fact_queue.empty()
    assert state == {
        "turn_id": "turn-current",
        "attempt": 1,
        "command": None,
        "state": "ready",
    }

    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "managed-session",
        _managed_user_fact(
            session_id="managed-session",
            turn_id="turn-current",
            delivery_attempt_no=1,
            runtime_command_id=202,
        ),
    )
    assert agent._fact_queue.qsize() == 1
    assert state["command"] == 202
    assert state["state"] == "admitted"
    assert acknowledgements == [101, 202]
    await manager.stop_all()


@pytest.mark.asyncio
async def test_ack_failure_retries_without_duplicate_agent_admission() -> None:
    admitted = False
    ack_attempts = 0

    async def admit(**_identity) -> bool:  # type: ignore[no-untyped-def]
        nonlocal admitted
        if admitted:
            return False
        admitted = True
        return True

    async def ack(_command_id: int) -> None:
        nonlocal ack_attempts
        ack_attempts += 1
        if ack_attempts == 1:
            raise RuntimeError("ack failed")

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NeverConsumeTaskAgent(
            TaskAgentType.CHAT,
            agent_id,
        ),
        user_message_delivery_admitter=admit,
        runtime_command_acknowledger=ack,
    )
    await manager.start_all(event_emitter=None)
    fact = _managed_user_fact(
        session_id="ack-retry",
        turn_id="turn-ack",
        delivery_attempt_no=0,
        runtime_command_id=303,
    )

    assert not await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "ack-retry",
        fact,
    )
    assert await manager.add_fact_to_agent(
        TaskAgentType.CHAT,
        "ack-retry",
        fact,
    )

    agent = manager.get_agent(TaskAgentType.CHAT, "ack-retry")
    assert agent is not None
    assert agent._fact_queue.qsize() == 1
    assert ack_attempts == 2
    await manager.stop_all()


@pytest.mark.asyncio
async def test_cancel_during_durable_admission_still_queues_fact_once() -> None:
    admission_started = asyncio.Event()
    release_admission = asyncio.Event()
    agent = _NeverConsumeTaskAgent(TaskAgentType.CHAT, "cancelled-admission")
    fact = _managed_user_fact(
        session_id="cancelled-admission",
        turn_id="turn-cancelled-admission",
        delivery_attempt_no=0,
        runtime_command_id=404,
    )

    async def admit() -> bool:
        admission_started.set()
        await release_admission.wait()
        return True

    admission = asyncio.create_task(
        agent.add_fact_with_admission(fact, admit=admit)
    )
    await asyncio.wait_for(admission_started.wait(), timeout=1)
    assert agent.has_inflight_work() is True
    admission.cancel()
    release_admission.set()
    with pytest.raises(asyncio.CancelledError):
        await admission

    assert agent._fact_queue.qsize() == 1
    duplicate = await agent.add_fact_with_admission(
        fact,
        admit=lambda: asyncio.sleep(0, result=False),
    )
    assert duplicate.superseded is True
    assert agent._fact_queue.qsize() == 1


@pytest.mark.asyncio
async def test_message_delete_hold_blocks_only_its_session() -> None:
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NeverConsumeTaskAgent(
            TaskAgentType.CHAT,
            agent_id,
        )
    )
    await manager.start_all(event_emitter=None)

    async with manager.hold_chat_session_for_message_delete(
        session_id="session-a",
        turn_id="turn-a",
        expected_run_id=None,
        expected_run_revision=0,
        match_turn_scope=True,
    ):
        waiting_a = asyncio.create_task(
            manager.add_fact_to_agent(
                TaskAgentType.CHAT,
                "session-a",
                _user_fact("session-a"),
            )
        )
        await asyncio.sleep(0)
        assert not waiting_a.done()

        assert await asyncio.wait_for(
            manager.add_fact_to_agent(
                TaskAgentType.CHAT,
                "session-b",
                _user_fact("session-b"),
            ),
            timeout=1,
        )
        assert manager.get_agent(TaskAgentType.CHAT, "session-b") is not None

    assert await asyncio.wait_for(waiting_a, timeout=1)
    assert manager.get_agent(TaskAgentType.CHAT, "session-a") is not None
    await manager.stop_all()


@pytest.mark.asyncio
async def test_message_delete_stops_newer_run_that_may_hold_deleted_context() -> None:
    cancellations: list[tuple[str, str | None]] = []

    class _ContextAwareAgent(TaskAgent):
        async def cancel_postprocess_for_destructive_change(self) -> None:
            return None

        async def plan_message_delete_runtime_turn_ids(
            self,
            *,
            session_id: str,
            turn_id: str,
        ) -> tuple[tuple[str, ...], tuple[str, ...]]:
            assert session_id == "session-context"
            assert turn_id == "turn-old"
            return ("turn-old", "turn-newer"), ()

        async def discard_pending_turn_for_message_delete(
            self,
            **_scope,
        ) -> bool:  # type: ignore[no-untyped-def]
            return False

        def matches_active_session_run(self, **_scope) -> bool:  # type: ignore[no-untyped-def]
            return False

        def active_root_turn_id_for_message_delete(
            self,
            *,
            session_id: str,
        ) -> str | None:
            assert session_id == "session-context"
            return "turn-newer"

        async def abandon_session_run_for_context_replay(
            self,
            *,
            session_id: str,
            replay_turn_ids: tuple[str, ...],
        ) -> bool:
            _ = (session_id, replay_turn_ids)
            return False

        async def request_session_cancel(self, **scope):  # type: ignore[no-untyped-def]
            cancellations.append(
                (str(scope["reason"]), scope.get("anchor_turn_id"))
            )
            return None

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _ContextAwareAgent(
            TaskAgentType.CHAT,
            agent_id,
        )
    )
    await manager.start_all(event_emitter=None)
    original = await manager.ensure_agent(
        TaskAgentType.CHAT,
        "session-context",
    )

    async with manager.hold_chat_session_for_message_delete(
        session_id="session-context",
        turn_id="turn-old",
        expected_run_id="run-old",
        expected_run_revision=0,
        match_turn_scope=True,
    ) as hold:
        assert hold.terminal_turn_ids == ("turn-old", "turn-newer")
        assert manager.get_agent(
            TaskAgentType.CHAT,
            "session-context",
        ) is original
        await hold.prepare_after_barrier()
        assert hold.cancelled_agent is True

    assert cancellations == [
        ("privacy_context_changed", "turn-newer")
    ]
    assert manager.get_agent(
        TaskAgentType.CHAT,
        "session-context",
    ) is None
    await manager.stop_all()


@pytest.mark.asyncio
async def test_message_delete_replays_batch_that_creates_root_after_plan() -> None:
    replay_cleanup: list[tuple[str, tuple[str, ...]]] = []
    cancellations: list[str] = []

    class _PreRunAgent(TaskAgent):
        active_root_turn_id: str | None = None

        async def cancel_postprocess_for_destructive_change(self) -> None:
            return None

        async def plan_message_delete_runtime_turn_ids(
            self,
            *,
            session_id: str,
            turn_id: str,
        ) -> tuple[tuple[str, ...], tuple[str, ...]]:
            assert session_id == "session-race"
            assert turn_id == "turn-old"
            assert self.active_root_turn_id is None
            return ("turn-old",), ("turn-new",)

        async def discard_pending_turn_for_message_delete(
            self,
            **_scope,
        ) -> bool:  # type: ignore[no-untyped-def]
            return False

        def matches_active_session_run(
            self,
            **_scope,
        ) -> bool:  # type: ignore[no-untyped-def]
            return False

        def active_root_turn_id_for_message_delete(
            self,
            *,
            session_id: str,
        ) -> str | None:
            assert session_id == "session-race"
            return self.active_root_turn_id

        async def abandon_session_run_for_context_replay(
            self,
            *,
            session_id: str,
            replay_turn_ids: tuple[str, ...],
        ) -> bool:
            replay_cleanup.append((session_id, replay_turn_ids))
            return True

        async def request_session_cancel(
            self,
            **scope,
        ):  # type: ignore[no-untyped-def]
            cancellations.append(str(scope["reason"]))
            return None

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _PreRunAgent(
            TaskAgentType.CHAT,
            agent_id,
        )
    )
    await manager.start_all(event_emitter=None)
    agent = await manager.ensure_agent(
        TaskAgentType.CHAT,
        "session-race",
    )
    assert isinstance(agent, _PreRunAgent)

    async with manager.hold_chat_session_for_message_delete(
        session_id="session-race",
        turn_id="turn-old",
        expected_run_id=None,
        expected_run_revision=0,
        match_turn_scope=True,
    ) as hold:
        assert hold.terminal_turn_ids == ("turn-old",)
        assert hold.replay_turn_ids == ("turn-new",)
        agent.active_root_turn_id = "turn-new"
        await hold.prepare_after_barrier()
        assert hold.cancelled_agent is True

    assert cancellations == []
    assert replay_cleanup == [
        ("session-race", ("turn-new",)),
    ]
    assert manager.get_agent(
        TaskAgentType.CHAT,
        "session-race",
    ) is None
    await manager.stop_all()
