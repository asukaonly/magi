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

from magi.core.runtime import (
    ActionExecutor,
    AgentRegistry,
    ChatAgentRunner,
    DailyReportAgentRunner,
    FactStore,
    MemoryDigestAgentRunner,
    RouterAgent,
    RuntimeOrchestrator,
    SensorHub,
    CHAT_AGENT_ID,
    DAILY_REPORT_AGENT_ID,
    MEMORY_DIGEST_AGENT_ID,
)
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.memory_backend import MemoryMessageBackend


class _FakeChatAgent:
    def __init__(self):
        self.called = 0
        self.last_user_id = None
        self.last_session_id = None

    async def execute_action(self, action):
        self.called += 1
        self.last_user_id = action.user_id
        self.last_session_id = action.session_id
        return {
            "success": True,
            "response": "ok",
            "user_id": action.user_id,
            "session_id": action.session_id,
        }


@pytest.mark.asyncio
async def test_runtime_chat_dispatch_from_message_bus():
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    fake_chat = _FakeChatAgent()
    sensor_hub = SensorHub(message_bus=message_bus)
    fact_store = FactStore()
    action_executor = ActionExecutor(chat_agent=fake_chat, message_bus=message_bus)
    registry = AgentRegistry()
    registry.register_runner(ChatAgentRunner(CHAT_AGENT_ID))
    registry.register_runner(MemoryDigestAgentRunner(MEMORY_DIGEST_AGENT_ID))
    registry.register_runner(DailyReportAgentRunner(DAILY_REPORT_AGENT_ID))
    router_agent = RouterAgent(sensor_hub=sensor_hub, agent_registry=registry, fact_store=fact_store)
    orchestrator = RuntimeOrchestrator(
        sensor_hub=sensor_hub,
        router_agent=router_agent,
        agent_registry=registry,
        fact_store=fact_store,
        action_executor=action_executor,
    )

    await orchestrator.start()
    await message_bus.publish(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"message": "你好", "user_id": "u-chat", "session_id": "s-chat"},
            source="test",
            level=EventLevel.INFO,
        )
    )

    await asyncio.sleep(0.4)
    await orchestrator.stop()
    await message_bus.stop()

    assert fake_chat.called >= 1
    assert fake_chat.last_user_id == "u-chat"
    assert fake_chat.last_session_id == "s-chat"
    stats = orchestrator.get_stats()
    assert stats["facts"].get(CHAT_AGENT_ID, 0) >= 1
