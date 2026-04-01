from __future__ import annotations

import asyncio
import json

import pytest

from magi.backend_app import create_backend_app


class _DummyTraceService:
    def get_trace_summary(self, *, user_id: str, session_id: str, turn_id: str) -> dict:
        raise AssertionError("sync trace reader should not be used")

    async def aget_trace_summary(self, *, user_id: str, session_id: str, turn_id: str) -> dict:
        assert user_id == "local_user"
        assert session_id == "session-1"
        assert turn_id == "turn-1"
        return {"trace_available": True, "headline": "done"}


class _FakeRuntimeTraceStore:
    def __init__(self) -> None:
        self._notifications = [
            {
                "notification_id": 1,
                "channel": "agent_response",
                "user_id": "local_user",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "payload_json": json.dumps(
                    {
                        "content": "hello",
                        "user_id": "local_user",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                    }
                ),
                "created_at_ms": 100,
            },
            {
                "notification_id": 2,
                "channel": "turn_ux_plan",
                "user_id": "local_user",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "payload_json": json.dumps(
                    {
                        "user_id": "local_user",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "ux_plan": {
                            "assistant_surface_mode": "interim_then_final",
                            "interim_text": "thinking",
                        },
                    }
                ),
                "created_at_ms": 101,
            },
            {
                "notification_id": 3,
                "channel": "execution_control",
                "user_id": "local_user",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "payload_json": json.dumps(
                    {
                        "user_id": "local_user",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "state": "cancelling",
                        "can_cancel": False,
                        "label": "Cancelling run",
                    }
                ),
                "created_at_ms": 102,
            },
            {
                "notification_id": 4,
                "channel": "execution_control",
                "user_id": "local_user",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "payload_json": json.dumps(
                    {
                        "user_id": "local_user",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "state": "cancelled",
                        "can_cancel": False,
                        "label": "Run cancelled",
                    }
                ),
                "created_at_ms": 103,
            },
            {
                "notification_id": 5,
                "channel": "context_usage",
                "user_id": "local_user",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "payload_json": json.dumps(
                    {
                        "user_id": "local_user",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "used_tokens": 45000,
                        "window_size": 128000,
                        "threshold": 96000,
                    }
                ),
                "created_at_ms": 104,
            },
        ]

    async def get_latest_notification_id(self) -> int:
        return 0

    async def list_notifications(self, *, after_id: int, limit: int = 50):
        _ = limit
        return [
            type("Notification", (), item)()
            for item in self._notifications
            if int(item["notification_id"]) > after_id
        ]


@pytest.mark.asyncio
async def test_websocket_bridge_polls_runtime_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_runtime_lifecycle(*args, **kwargs) -> None:
        return None

    broadcasts: list[tuple[str, dict, str | None]] = []

    async def _capture_broadcast(event: str, data: dict, room: str | None = None) -> None:
        broadcasts.append((event, data, room))

    monkeypatch.setattr("magi.backend_app.initialize_agent_runtime", _noop_runtime_lifecycle)
    monkeypatch.setattr("magi.backend_app.shutdown_agent_runtime", _noop_runtime_lifecycle)
    monkeypatch.setattr("magi.websocket.bridge_lifecycle.get_chat_trace_read_service", lambda: _DummyTraceService())
    monkeypatch.setattr(
        "magi.websocket.bridge_lifecycle.require_runtime_trace_store",
        lambda: _FakeRuntimeTraceStore(),
    )
    monkeypatch.setattr("magi.websocket.bridge_lifecycle.manager.broadcast", _capture_broadcast)
    monkeypatch.setattr(
        "magi.websocket.bridge_lifecycle.DEFAULT_WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS",
        0.01,
    )

    app = create_backend_app()
    async with app.router.lifespan_context(app):
        for _ in range(100):
            if broadcasts:
                break
            await asyncio.sleep(0.01)

    assert broadcasts
    assert broadcasts[0][0] == "agent_response"
    assert broadcasts[0][1]["content"] == "hello"
    assert broadcasts[0][1]["trace_summary"]["headline"] == "done"
    assert broadcasts[0][1]["trace_available"] is True
    assert broadcasts[0][2] == "user_local_user"
    assert broadcasts[1][0] == "turn_ux_plan"
    assert broadcasts[1][1]["ux_plan"]["assistant_surface_mode"] == "interim_then_final"
    assert broadcasts[2][0] == "turn_execution_control"
    assert broadcasts[2][1]["state"] == "cancelling"
    assert broadcasts[2][1]["can_cancel"] is False
    assert broadcasts[3][0] == "turn_execution_control"
    assert broadcasts[3][1]["state"] == "cancelled"
    assert broadcasts[4][0] == "context_usage"
    assert broadcasts[4][1]["used_tokens"] == 45000
    assert broadcasts[4][1]["window_size"] == 128000
    assert broadcasts[4][1]["threshold"] == 96000
    assert broadcasts[4][1]["session_id"] == "session-1"
