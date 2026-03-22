from __future__ import annotations

import pytest

from magi.chat.read_service import ChatDisplayMessage
from magi.api.services.message_dispatch_service import MessageDispatchOutcome
from magi.websocket.handlers import WebSocketContext, handle_get_history, handle_send_message


class _DummyWebSocket:
    async def send_json(self, message: dict) -> None:
        _ = message


class _DummyManager:
    def join_room(self, sid: str, channel: str) -> None:
        _ = (sid, channel)

    def leave_room(self, sid: str, channel: str) -> None:
        _ = (sid, channel)


@pytest.mark.asyncio
async def test_handle_send_message_passes_runtime_namespace_to_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_dispatch_user_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return MessageDispatchOutcome(
            success=True,
            user_id=str(kwargs["user_id"]),
            session_id="session-1",
            turn_id="turn-1",
        )

    monkeypatch.setattr("magi.api.services.dispatch_user_message", _fake_dispatch_user_message)

    ctx = WebSocketContext(
        sid="sid-1",
        websocket=_DummyWebSocket(),  # type: ignore[arg-type]
        manager=_DummyManager(),  # type: ignore[arg-type]
    )

    response = await handle_send_message(
        ctx,
        {
            "user_id": "asuka_main",
            "message": "hello",
            "session_id": "session-1",
            "metadata": {"runtime_namespace": "telegram"},
        },
    )

    assert response["type"] == "message_sent"
    assert captured["runtime_namespace"] == "telegram"


@pytest.mark.asyncio
async def test_handle_get_history_uses_async_read_service(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr("magi.websocket.handlers.get_chat_read_service", lambda: _AsyncOnlyReadService())

    ctx = WebSocketContext(
        sid="sid-1",
        websocket=_DummyWebSocket(),  # type: ignore[arg-type]
        manager=_DummyManager(),  # type: ignore[arg-type]
    )

    response = await handle_get_history(ctx, {"user_id": "u1", "session_id": "s1"})

    assert response["type"] == "history"
    assert response["data"]["messages"][0]["content"] == "hello"
