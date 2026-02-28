import asyncio

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover - allows running in minimal envs
    class _Mark:
        @staticmethod
        def asyncio(func):
            return func

    class _PytestFallback:
        mark = _Mark()

    pytest = _PytestFallback()

from magi.core.layers import (
    ActionLayer,
    FiveLayerCoordinator,
    RouterLayer,
    SensorLayer,
    TaskLayer,
    WorkerLayer,
)
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.memory_backend import MemoryMessageBackend


class _FakeChatAgent:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.actions = []

    async def execute_action(self, action):
        self.actions.append(action)
        if self.should_fail:
            raise RuntimeError("chat failure")
        return {
            "success": True,
            "response": "ok",
            "user_id": action.user_id,
            "session_id": action.session_id,
        }


@pytest.mark.asyncio
async def test_five_layer_chat_flow_success():
    message_bus = MemoryMessageBackend()
    await message_bus.start()
    fake_agent = _FakeChatAgent()

    coordinator_ref = {"instance": None}

    async def on_context(ctx):
        await coordinator_ref["instance"].on_sensor_context(ctx)

    sensor = SensorLayer(message_bus=message_bus, on_context=on_context)
    coordinator = FiveLayerCoordinator(
        sensor_layer=sensor,
        router_layer=RouterLayer(),
        task_layer=TaskLayer(task_database=None),
        worker_layer=WorkerLayer(action_layer=ActionLayer(chat_agent=fake_agent, message_bus=message_bus)),
    )
    coordinator_ref["instance"] = coordinator
    await coordinator.start()

    await message_bus.publish(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "message": "你好，帮我总结一下今天安排",
                "user_id": "u1",
                "session_id": "s1",
            },
            source="test",
            level=EventLevel.INFO,
        )
    )

    await asyncio.sleep(0.2)
    await coordinator.stop()
    await message_bus.stop()

    assert len(fake_agent.actions) == 1
    assert fake_agent.actions[0].user_id == "u1"
    assert fake_agent.actions[0].session_id == "s1"
    assert coordinator.get_stats()["processed"] == 1


@pytest.mark.asyncio
async def test_five_layer_chat_flow_failure_fallback():
    message_bus = MemoryMessageBackend()
    await message_bus.start()
    fake_agent = _FakeChatAgent(should_fail=True)

    coordinator_ref = {"instance": None}

    async def on_context(ctx):
        await coordinator_ref["instance"].on_sensor_context(ctx)

    sensor = SensorLayer(message_bus=message_bus, on_context=on_context)
    coordinator = FiveLayerCoordinator(
        sensor_layer=sensor,
        router_layer=RouterLayer(),
        task_layer=TaskLayer(task_database=None),
        worker_layer=WorkerLayer(action_layer=ActionLayer(chat_agent=fake_agent, message_bus=message_bus)),
    )
    coordinator_ref["instance"] = coordinator
    await coordinator.start()

    await message_bus.publish(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"message": "hello", "user_id": "u2", "session_id": "s2"},
            source="test",
            level=EventLevel.INFO,
        )
    )

    await asyncio.sleep(0.2)
    await coordinator.stop()
    await message_bus.stop()

    assert len(fake_agent.actions) == 1
    assert coordinator.get_stats()["failed"] == 1
