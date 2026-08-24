"""End-to-end runtime user-message admission and acknowledgement coverage."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from magi.agent.runtime.router_agent import RouterAgent
from magi.agent.runtime.task_agent import TaskAgent
from magi.agent.runtime.task_agent_manager import TaskAgentManager
from magi.agent.runtime.types import TaskAgentType
from magi.awareness.sensor_hub import SensorHub
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.chat import ChatStore
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.events.contracts import UserMessageCommand
from magi.events.events import EventTypes
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.events.lifecycle import RuntimeCommandProcessorModule
from magi.events.runtime_queue import SQLiteRuntimeCommandQueue


class _RecordingChatAgent(TaskAgent):
    def __init__(self, agent_id: str, processed: list[int]) -> None:
        super().__init__(TaskAgentType.CHAT, agent_id)
        self._processed_commands = processed

    async def finalize_result(self, context, result) -> None:  # type: ignore[no-untyped-def]
        _ = result
        fact = context.latest_fact
        if fact is not None and fact.runtime_command_id is not None:
            self._processed_commands.append(fact.runtime_command_id)


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


@pytest.mark.asyncio
async def test_cancel_queued_turn_before_runtime_admission_converges_without_execution(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    created = await chat_store.create_user_turn_once(
        session_id="session-queued-cancel",
        user_id="user-queued-cancel",
        turn_id="turn-queued-cancel",
        message_text="Do not execute after I stop this",
        created_at_ms=1710000000000,
        runtime_envelope={
            "source": "api",
            "user_id": "user-queued-cancel",
            "session_id": "session-queued-cancel",
            "turn_id": "turn-queued-cancel",
            "message": "Do not execute after I stop this",
            "attachments": [],
            "workspace_path": None,
            "interaction_kind": None,
            "metadata": {},
            "runtime_namespace": "desktop",
        },
        request_fingerprint="queued-cancel-request",
    )
    await chat_store.mark_user_turn_projection_completed(
        turn_id="turn-queued-cancel",
        updated_at_ms=1710000000001,
    )

    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path),
    )
    await queue.start()
    command_id = await queue.enqueue_user_message(
        UserMessageCommand(
            source="api",
            user_id="user-queued-cancel",
            session_id="session-queued-cancel",
            turn_id="turn-queued-cancel",
            message="Do not execute after I stop this",
            runtime_namespace="desktop",
            correlation_id=f"user_message:{created.message.message_id}",
        )
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id="turn-queued-cancel",
        delivery_attempt_no=0,
        command_id=command_id,
        updated_at_ms=1710000000002,
    )

    cancel_agent = ChatTaskAgent(
        agent_id="session-queued-cancel",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )

    async def _ignore_control_notification(**_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        cancel_agent._postprocess_service,
        "emit_execution_control_notification",
        _ignore_control_notification,
    )
    first_cancel = await cancel_agent.request_session_cancel(
        session_id="session-queued-cancel",
        user_id="user-queued-cancel",
        requested_by="user",
        anchor_turn_id="turn-queued-cancel",
    )
    repeated_cancel = await cancel_agent.request_session_cancel(
        session_id="session-queued-cancel",
        user_id="user-queued-cancel",
        requested_by="user",
        anchor_turn_id="turn-queued-cancel",
    )
    assert first_cancel is not None
    assert first_cancel["status"] == "cancelled"
    assert repeated_cancel is not None
    assert repeated_cancel["status"] == "cancelled"

    message_bus = InMemoryMessageBusBackend(num_workers=1, max_queue_size=64)
    await message_bus.start()
    sensor_hub = SensorHub(message_bus)
    await sensor_hub.start()
    processed_commands: list[int] = []
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _RecordingChatAgent(
            agent_id,
            processed_commands,
        ),
        user_message_delivery_admitter=chat_store.mark_user_turn_delivery_admitted,
        runtime_command_acknowledger=queue.ack,
    )
    await manager.start_all(event_emitter=None, sensor_hub=sensor_hub)
    router = RouterAgent(
        sensor_hub=sensor_hub,
        task_agent_manager=manager,
        poll_timeout_seconds=0.01,
        restart_backoff_seconds=0.01,
    )
    await router.start()
    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.005)
    await processor.init()

    try:
        for _ in range(400):
            if (await queue.get_stats())["completed_count"] == 1:
                break
            await asyncio.sleep(0.01)

        turn = await chat_store.get_turn("turn-queued-cancel")
        delivery = await chat_store.get_user_turn_delivery(
            turn_id="turn-queued-cancel",
        )
        assert turn is not None
        assert turn.status == "cancelled"
        assert delivery is not None
        assert delivery.delivery_state == "terminal"
        assert processed_commands == []
        assert (await queue.get_stats())["completed_count"] == 1
    finally:
        await processor.shutdown()
        await router.stop()
        await manager.stop_all()
        await sensor_hub.stop()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_ack_failure_replays_same_command_without_double_admission(
    tmp_path: Path,
) -> None:
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(tmp_path / "runtime_commands.db"),
        claim_lease_seconds=0.02,
    )
    await queue.start()
    message_bus = InMemoryMessageBusBackend(num_workers=1, max_queue_size=64)
    await message_bus.start()
    sensor_hub = SensorHub(message_bus)
    await sensor_hub.start()

    processed_commands: list[int] = []
    admitted: set[tuple[str, int, int]] = set()
    admission_calls: list[tuple[str, int, int]] = []
    ack_calls: list[int] = []
    published_event_ids: list[str] = []

    async def _admit(
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool:
        _ = updated_at_ms
        identity = (turn_id, delivery_attempt_no, command_id)
        admission_calls.append(identity)
        if identity in admitted:
            return False
        admitted.add(identity)
        return True

    async def _ack_with_one_failure(command_id: int) -> None:
        ack_calls.append(command_id)
        if len(ack_calls) == 1:
            raise RuntimeError("simulated acknowledgement failure")
        await queue.ack(command_id)

    async def _record_publish(event) -> None:  # type: ignore[no-untyped-def]
        if event.event_id is not None:
            published_event_ids.append(event.event_id)

    await message_bus.subscribe(
        EventTypes.USER_MESSAGE,
        _record_publish,
        propagation_mode="broadcast",
    )
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _RecordingChatAgent(
            agent_id,
            processed_commands,
        ),
        user_message_delivery_admitter=_admit,
        runtime_command_acknowledger=_ack_with_one_failure,
    )
    await manager.start_all(event_emitter=None, sensor_hub=sensor_hub)
    router = RouterAgent(
        sensor_hub=sensor_hub,
        task_agent_manager=manager,
        poll_timeout_seconds=0.01,
        restart_backoff_seconds=0.01,
    )
    await router.start()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.005)
    await processor.init()

    try:
        command_id = await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                message="deliver exactly once to the agent queue",
                correlation_id="user_message:message-1",
            )
        )

        for _ in range(400):
            stats = await queue.get_stats()
            if stats["completed_count"] == 1 and len(processed_commands) == 1:
                break
            await asyncio.sleep(0.01)

        processor.begin_draining()
        await processor.wait_until_idle(timeout_seconds=1.0)
        for _ in range(100):
            bus_stats = await message_bus.get_stats()
            if bus_stats["queue_length"] == 0 and bus_stats["active_dispatches"] == 0:
                break
            await asyncio.sleep(0.01)

        assert (await queue.get_stats())["completed_count"] == 1
        assert processed_commands == [command_id]
        expected_identity = ("turn-1", 0, command_id)
        assert len(admission_calls) >= 2
        assert set(admission_calls) == {expected_identity}
        assert admitted == {expected_identity}
        assert len(ack_calls) == len(admission_calls)
        assert set(ack_calls) == {command_id}
        assert len(published_event_ids) == len(admission_calls)
        assert len(set(published_event_ids)) == 1
    finally:
        await processor.shutdown()
        await router.stop()
        await manager.stop_all()
        await sensor_hub.stop()
        await message_bus.stop()
        await queue.stop()
