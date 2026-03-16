from __future__ import annotations

import pytest

from magi.api.routers import messages as messages_router


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
