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
    AgentRuntime,
    ChatTaskAgent,
    DailyReportTaskAgent,
    MemoryDigestTaskAgent,
    RouterAgent,
    SensorHub,
    TaskAgentManager,
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
    action_executor = ActionExecutor(chat_agent=fake_chat, message_bus=message_bus)
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: ChatTaskAgent(agent_id),
        create_memory_digest_agent=lambda agent_id: MemoryDigestTaskAgent(agent_id),
        create_daily_report_agent=lambda agent_id: DailyReportTaskAgent(agent_id),
    )
    router_agent = RouterAgent(sensor_hub=sensor_hub, task_agent_manager=manager)
    orchestrator = AgentRuntime(
        sensor_hub=sensor_hub,
        router_agent=router_agent,
        task_agent_manager=manager,
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
    stats = orchestrator.get_stats()
    await orchestrator.stop()
    await message_bus.stop()

    assert fake_chat.called >= 1
    assert fake_chat.last_user_id == "u-chat"
    assert fake_chat.last_session_id == "s-chat"
    assert any(key.startswith("chat:") for key in stats["agents"]["instances"].keys())
