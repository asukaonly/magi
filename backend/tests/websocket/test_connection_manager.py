from __future__ import annotations

import pytest

from magi.websocket.connection_manager import ConnectionManager


class _DummyWebSocket:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent_messages.append(message)


@pytest.mark.asyncio
async def test_broadcast_agent_response_to_room_does_not_raise() -> None:
    manager = ConnectionManager()
    ws = _DummyWebSocket()
    sid = "sid-1"
    room = "user_web_user"

    manager.active_connections[sid] = ws
    manager.connection_rooms[sid] = {room}
    manager.rooms[room] = {sid}

    await manager.broadcast("agent_response", {"response": "ok"}, room=room)

    assert len(ws.sent_messages) == 1
    assert ws.sent_messages[0]["event"] == "agent_response"
    assert ws.sent_messages[0]["data"]["response"] == "ok"
