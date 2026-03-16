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

from magi.awareness.action_emitter import ActionEmitter
from magi.core.runtime import (
    AgentRuntime,
    RouterAgent,
    SensorHub,
    TaskAgent,
    TaskAgentExecutionRequest,
    TaskAgentIntentResult,
    TaskAgentRuntimeContext,
    TaskAgentToolSelection,
    TaskAgentManager,
    TaskAgentType,
)
from magi.core.runtime.contracts import FactRecord
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.memory_backend import MemoryMessageBackend


class _FakeChatTaskAgent(
    TaskAgent[
        TaskAgentRuntimeContext,
        TaskAgentIntentResult,
        TaskAgentToolSelection,
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

    async def call_llm(self, context: TaskAgentRuntimeContext, llm_params: TaskAgentExecutionRequest) -> dict:
        _ = (context, llm_params)
        self.called += 1
        return {"response": "ok"}

    async def parse_result(self, context: TaskAgentRuntimeContext, raw_result):
        if self._action_emitter is None:
            return
        latest = context.latest_fact
        if isinstance(latest, FactRecord):
            await self._action_emitter.emit_action_event(latest, success=True)


@pytest.mark.asyncio
async def test_runtime_chat_dispatch_from_message_bus():
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    fake_chat = _FakeChatTaskAgent()
    sensor_hub = SensorHub(message_bus=message_bus)
    action_emitter = ActionEmitter(message_bus=message_bus)
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: fake_chat if agent_id == "u-chat" else _FakeChatTaskAgent(),
    )
    router_agent = RouterAgent(sensor_hub=sensor_hub, task_agent_manager=manager)
    orchestrator = AgentRuntime(
        sensor_hub=sensor_hub,
        router_agent=router_agent,
        task_agent_manager=manager,
        action_emitter=action_emitter,
    )

    await orchestrator.start()
    await message_bus.publish(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"message": "你好", "user_id": "u-chat", "session_id": "s-chat", "turn_id": "turn_1"},
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
