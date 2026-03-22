from __future__ import annotations

import pytest

from magi.api.routers import messages as messages_router
from magi.chat.read_service import ChatDisplayMessage
from magi.api.services.message_dispatch_service import MessageDispatchOutcome


class _FakeQueue:
    def qsize(self) -> int:
        return 7


class _FakeSensor:
    def __init__(self) -> None:
        self.enabled = True
        self.perception_type = type("PerceptionType", (), {"value": "user_message"})()
        self.trigger_mode = type("TriggerMode", (), {"value": "event"})()
        self._queue = _FakeQueue()
        self.actions: list[str] = []

    def get_queue(self):
        return self._queue

    def enable(self) -> None:
        self.actions.append("enable")
        self.enabled = True

    def disable(self) -> None:
        self.actions.append("disable")
        self.enabled = False


@pytest.mark.asyncio
async def test_sensor_status_uses_bound_user_message_sensor(monkeypatch: pytest.MonkeyPatch) -> None:
    sensor = _FakeSensor()
    monkeypatch.setattr(messages_router, "require_user_message_sensor", lambda: sensor)

    response = await messages_router.get_sensor_status()

    assert response["enabled"] is True
    assert response["queue_size"] == 7


@pytest.mark.asyncio
async def test_enable_sensor_uses_bound_user_message_sensor(monkeypatch: pytest.MonkeyPatch) -> None:
    sensor = _FakeSensor()
    monkeypatch.setattr(messages_router, "require_user_message_sensor", lambda: sensor)

    response = await messages_router.enable_sensor()

    assert response["success"] is True
    assert sensor.actions == ["enable"]


@pytest.mark.asyncio
async def test_disable_sensor_uses_bound_user_message_sensor(monkeypatch: pytest.MonkeyPatch) -> None:
    sensor = _FakeSensor()
    monkeypatch.setattr(messages_router, "require_user_message_sensor", lambda: sensor)

    response = await messages_router.disable_sensor()

    assert response["success"] is True
    assert sensor.actions == ["disable"]


@pytest.mark.asyncio
async def test_send_user_message_uses_runtime_namespace_for_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr(messages_router, "dispatch_user_message", _fake_dispatch_user_message)

    response = await messages_router.send_user_message(
        messages_router.UserMessageRequest(
            message="hello",
            user_id="asuka_main",
            metadata={"runtime_namespace": "telegram"},
        )
    )

    assert response.success is True
    assert captured["runtime_namespace"] == "telegram"


@pytest.mark.asyncio
async def test_get_conversation_history_uses_async_read_service(monkeypatch: pytest.MonkeyPatch) -> None:
    class _AsyncOnlyReadService:
        def get_display_history(self, user_id: str, session_id: str):  # type: ignore[no-untyped-def]
            raise AssertionError("sync history reader should not be used")

        async def aget_display_history(self, user_id: str, session_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            return [
                ChatDisplayMessage(
                    role="assistant",
                    content="hello",
                    timestamp=1,
                    kind="assistant",
                )
            ]

    monkeypatch.setattr(messages_router, "get_chat_read_service", lambda: _AsyncOnlyReadService())

    response = await messages_router.get_conversation_history(user_id="u1", session_id="s1")

    assert response["count"] == 1
    assert response["messages"][0]["content"] == "hello"


@pytest.mark.asyncio
async def test_get_execution_trace_uses_async_trace_service(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeReadService:
        pass

    class _AsyncOnlyTraceService:
        def get_trace_snapshot(self, *, user_id: str, session_id: str, turn_id: str):
            raise AssertionError("sync trace reader should not be used")

        async def aget_trace_snapshot(self, *, user_id: str, session_id: str, turn_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            assert turn_id == "turn-1"
            return {"summary": {"headline": "done"}}

    monkeypatch.setattr(messages_router, "get_chat_read_service", lambda: _FakeReadService())
    monkeypatch.setattr(messages_router, "get_chat_trace_read_service", lambda: _AsyncOnlyTraceService())

    response = await messages_router.get_execution_trace(user_id="u1", session_id="s1", turn_id="turn-1")

    assert response["success"] is True
    assert response["trace"]["summary"]["headline"] == "done"
