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
from magi.awareness.contracts import ActionEmissionRecord
from magi.awareness.sensor_hub import SensorHub
from magi.agent.runtime import (
    AgentRuntime,
    RouterAgent,
    TaskAgent,
    TaskAgentExecutionRequest,
    TaskAgentIntentResult,
    TaskAgentRuntimeContext,
    TaskAgentToolSelection,
    TaskAgentManager,
    TaskAgentType,
)
from magi.agent.runtime.contracts import FactRecord
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.sqlite_backend import SQLiteMessageBackend


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
            await self._action_emitter.emit_action_event(
                ActionEmissionRecord(
                    agent_id=latest.agent_id,
                    event_type=latest.event_type,
                    payload=latest.payload if isinstance(latest.payload, dict) else {},
                    correlation_id=latest.correlation_id,
                ),
                success=True,
            )


@pytest.mark.asyncio
async def test_runtime_chat_dispatch_from_message_bus(tmp_path):
    message_bus = SQLiteMessageBackend(db_path=str(tmp_path / "message_queue.db"), num_workers=1)
    await message_bus.start()

    fake_chat = _FakeChatTaskAgent()
    sensor_hub = SensorHub(message_bus=message_bus)
    action_emitter = ActionEmitter(message_bus=message_bus)
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: fake_chat if agent_id == "s-chat" else _FakeChatTaskAgent(),
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
            data={"content": "你好", "user_id": "u-chat", "session_id": "s-chat", "turn_id": "turn_1"},
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
async def test_sensor_hub_preserves_runtime_namespace_from_user_messages(tmp_path):
    message_bus = SQLiteMessageBackend(db_path=str(tmp_path / "message_queue.db"), num_workers=1)
    await message_bus.start()

    sensor_hub = SensorHub(message_bus=message_bus)
    await sensor_hub.start()
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

        batch = await sensor_hub.get_batch(timeout_seconds=0.4)
    finally:
        await sensor_hub.stop()
        await message_bus.stop()

    assert len(batch) == 1
    assert batch[0].payload["content"] == "你好"
    assert batch[0].payload["runtime_namespace"] == "telegram"
