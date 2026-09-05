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

from magi.awareness.event_emitter import RuntimeEventEmitter
from magi.awareness.source_hub import SourceHub
from magi.agent.runtime import (
    AgentRuntime,
    RouterAgent,
    TaskAgent,
    TaskAgentAdmissionDecision,
    TaskAgentCapabilitySelection,
    TaskAgentExecutionRequest,
    TaskAgentRuntimeContext,
    TaskAgentManager,
    TaskAgentType,
)
from magi.agent.runtime.contracts import FactRecord
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.in_memory_backend import InMemoryMessageBusBackend


class _FakeChatTaskAgent(
    TaskAgent[
        TaskAgentRuntimeContext,
        TaskAgentAdmissionDecision,
        TaskAgentCapabilitySelection,
        TaskAgentExecutionRequest,
        dict,
    ]
):
    def __init__(self):
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id="default")
        self.called = 0
        self.last_user_id = None
        self.last_session_id = None
        self.last_turn_id = None

    async def build_context(self, merged_facts: list[FactRecord]) -> TaskAgentRuntimeContext:
        context = await super().build_context(merged_facts)
        latest = context.latest_fact
        payload = latest.payload if isinstance(latest, FactRecord) else {}
        self.last_user_id = payload.get("user_id")
        self.last_session_id = payload.get("session_id")
        self.last_turn_id = payload.get("turn_id")
        return context

    async def execute_request(
        self,
        context: TaskAgentRuntimeContext,
        request: TaskAgentExecutionRequest,
    ) -> dict:
        _ = (context, request)
        self.called += 1
        return {"response": "ok"}

    async def finalize_result(self, context: TaskAgentRuntimeContext, result):
        _ = result
        if self._event_emitter is None:
            return
        latest = context.latest_fact
        if isinstance(latest, FactRecord):
            await self._event_emitter.emit_runtime_event(
                event_type=latest.event_type,
                payload=latest.payload if isinstance(latest.payload, dict) else {},
                correlation_id=latest.correlation_id,
                success=True,
            )


@pytest.mark.asyncio
async def test_runtime_chat_dispatch_from_message_bus(tmp_path):
    message_bus = InMemoryMessageBusBackend(num_workers=1)
    await message_bus.start()

    fake_chat = _FakeChatTaskAgent()
    source_hub = SourceHub(message_bus=message_bus)
    event_emitter = RuntimeEventEmitter(message_bus=message_bus)
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: fake_chat
        if agent_id == "s-chat"
        else _FakeChatTaskAgent(),
    )
    router_agent = RouterAgent(source_hub=source_hub, task_agent_manager=manager)
    orchestrator = AgentRuntime(
        source_hub=source_hub,
        router_agent=router_agent,
        task_agent_manager=manager,
        event_emitter=event_emitter,
    )

    await orchestrator.start()
    await message_bus.publish(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "content": "你好",
                "user_id": "u-chat",
                "session_id": "s-chat",
                "turn_id": "turn_1",
            },
            source="test",
            level=EventLevel.INFO,
        )
    )

    await asyncio.sleep(0.4)
    stats = orchestrator.get_stats()
    await orchestrator.stop()
    await message_bus.stop()

    assert fake_chat.called >= 1
    assert fake_chat.last_user_id == "u-chat"
    assert fake_chat.last_session_id == "s-chat"
    assert fake_chat.last_turn_id == "turn_1"
    assert any(key.startswith("chat:") for key in stats["agents"]["instances"].keys())


@pytest.mark.asyncio
async def test_source_hub_preserves_runtime_namespace_from_user_messages(tmp_path):
    message_bus = InMemoryMessageBusBackend(num_workers=1)
    await message_bus.start()

    source_hub = SourceHub(message_bus=message_bus)
    await source_hub.start()
    try:
        await message_bus.publish(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "content": "你好",
                    "user_id": "asuka_main",
                    "runtime_namespace": "telegram",
                    "session_id": "s-chat",
                    "turn_id": "turn_2",
                },
                source="websocket",
                level=EventLevel.INFO,
            )
        )

        batch = await source_hub.get_batch(timeout_seconds=0.4)
    finally:
        await source_hub.stop()
        await message_bus.stop()

    assert len(batch) == 1
    assert batch[0].payload["content"] == "你好"
    assert batch[0].payload["runtime_namespace"] == "telegram"
