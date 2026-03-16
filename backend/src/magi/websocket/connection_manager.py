"""
WebSocket connection management for the transport layer.
"""
from __future__ import annotations

from typing import Dict, Set

from fastapi import WebSocket

from ..core.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """WebSocket connection manager with room support."""

    def __init__(self) -> None:
        self.active_connections: Dict[str, WebSocket] = {}
        self.rooms: Dict[str, Set[str]] = {}
        self.connection_rooms: Dict[str, Set[str]] = {}

    async def connect(self, sid: str, websocket: WebSocket) -> None:
        """Accept a WebSocket connection."""
        await websocket.accept()
        self.active_connections[sid] = websocket
        self.connection_rooms[sid] = set()
        logger.info("WebSocket connected", sid=sid, total=len(self.active_connections))

    def disconnect(self, sid: str) -> None:
        """Disconnect a WebSocket connection."""
        if sid in self.active_connections:
            if sid in self.connection_rooms:
                for room in list(self.connection_rooms[sid]):
                    self.leave_room(sid, room)

            del self.active_connections[sid]
            del self.connection_rooms[sid]
            logger.info("WebSocket disconnected", sid=sid, total=len(self.active_connections))

    async def send_to_connection(self, sid: str, message: dict) -> bool:
        """Send a message to a specific connection."""
        if sid in self.active_connections:
            try:
                await self.active_connections[sid].send_json(message)
                return True
            except Exception as exc:
                logger.error("Failed to send", sid=sid, error=str(exc))
                self.disconnect(sid)
                return False
        return False

    async def broadcast(self, event: str, data: dict, room: str | None = None) -> None:
        """Broadcast a message to all connections or a room."""
        message = {
            "event": event,
            "data": data,
        }

        if room:
            targets = list(self.rooms.get(room, set()))
        else:
            targets = list(self.active_connections.keys())

        success_count = 0
        for sid in targets:
            if await self.send_to_connection(sid, message):
                success_count += 1

        failed_count = len(targets) - success_count
        log_method = logger.info if event in {"agent_response", "execution_trace_update"} else logger.debug
        log_method(
            "Broadcast dispatched",
            ws_event=event,
            room=room or "__all__",
            targets=len(targets),
            success=success_count,
            failed=failed_count,
        )

    def join_room(self, sid: str, room: str) -> None:
        """Join a room."""
        if sid not in self.active_connections:
            return

        if room not in self.rooms:
            self.rooms[room] = set()

        self.rooms[room].add(sid)
        self.connection_rooms[sid].add(room)
        logger.info("Client joined room", sid=sid, room=room)

    def leave_room(self, sid: str, room: str) -> None:
        """Leave a room."""
        if room in self.rooms:
            self.rooms[room].discard(sid)
            if not self.rooms[room]:
                del self.rooms[room]

        if sid in self.connection_rooms:
            self.connection_rooms[sid].discard(room)

        logger.info("Client left room", sid=sid, room=room)

    def get_client_count(self) -> int:
        """Get the number of connected clients."""
        return len(self.active_connections)

    def get_clients_in_room(self, room: str) -> int:
        """Get the number of clients in a room."""
        return len(self.rooms.get(room, set()))

    def get_connection_rooms(self, sid: str) -> Set[str]:
        """Get all rooms a connection has joined."""
        return self.connection_rooms.get(sid, set())

    async def broadcast_to_user(self, user_id: str, message: dict) -> None:
        """Broadcast a message to all connections in a user's room."""
        await self.broadcast("user_message", message, room=f"user_{user_id}")


manager = ConnectionManager()


async def broadcast_agent_update(agent_id: str, state: str, data: dict | None = None) -> None:
    """Broadcast an agent update."""
    await manager.broadcast(
        "agent_update",
        {
            "type": "agent_update",
            "agent_id": agent_id,
            "state": state,
            "data": data or {},
        },
    )


async def broadcast_task_update(task_id: str, state: str, data: dict | None = None) -> None:
    """Broadcast a task update."""
    await manager.broadcast(
        "task_update",
        {
            "type": "task_update",
            "task_id": task_id,
            "state": state,
            "data": data or {},
        },
    )


async def broadcast_metrics_update(metrics: dict) -> None:
    """Broadcast a metrics update."""
    await manager.broadcast(
        "metrics_update",
        {
            "type": "metrics_update",
            "metrics": metrics,
        },
    )


async def broadcast_log(level: str, message: str, source: str | None = None) -> None:
    """Broadcast a log message."""
    await manager.broadcast(
        "log",
        {
            "type": "log",
            "level": level,
            "message": message,
            "source": source,
        },
    )
