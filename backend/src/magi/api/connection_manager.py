"""
FastAPI WebSocket integration.

Provides WebSocket support for the FastAPI application.
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Dict, Set
import json

from ..core.logger import get_logger

logger = get_logger(__name__)


# Connection manager (supports rooms)
class ConnectionManager:
    """WebSocket connection manager with room support."""

    def __init__(self):
        # Active connections {sid: websocket}
        self.active_connections: Dict[str, WebSocket] = {}

        # Room members {room: set of sids}
        self.rooms: Dict[str, Set[str]] = {}

        # Rooms for each connection {sid: set of rooms}
        self.connection_rooms: Dict[str, Set[str]] = {}

    async def connect(self, sid: str, websocket: WebSocket):
        """Accept a WebSocket connection."""
        await websocket.accept()
        self.active_connections[sid] = websocket
        self.connection_rooms[sid] = set()
        logger.info("WebSocket connected", sid=sid, total=len(self.active_connections))

    def disconnect(self, sid: str):
        """Disconnect a WebSocket connection."""
        if sid in self.active_connections:
            # Leave all rooms
            if sid in self.connection_rooms:
                for room in list(self.connection_rooms[sid]):
                    self.leave_room(sid, room)

            del self.active_connections[sid]
            del self.connection_rooms[sid]
            logger.info("WebSocket disconnected", sid=sid, total=len(self.active_connections))

    async def send_to_connection(self, sid: str, message: dict):
        """Send a message to a specific connection."""
        if sid in self.active_connections:
            try:
                await self.active_connections[sid].send_json(message)
            except Exception as e:
                logger.error("Failed to send", sid=sid, error=str(e))
                self.disconnect(sid)

    async def broadcast(self, event: str, data: dict, room: str = None):
        """
        Broadcast a message.

        Args:
            event: Event name.
            data: data
            room: Room name (optional).
        """
        message = {
            "event": event,
            "data": data
        }

        if room:
            # Send to all connections in the room
            if room in self.rooms:
                for sid in list(self.rooms[room]):
                    await self.send_to_connection(sid, message)
        else:
            # Broadcast to all connections
            for sid in list(self.active_connections.keys()):
                await self.send_to_connection(sid, message)

    def join_room(self, sid: str, room: str):
        """Join a room."""
        if sid not in self.active_connections:
            return

        if room not in self.rooms:
            self.rooms[room] = set()

        self.rooms[room].add(sid)
        self.connection_rooms[sid].add(room)
        logger.info("Client joined room", sid=sid, room=room)

    def leave_room(self, sid: str, room: str):
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
        """Get all rooms that a connection has joined."""
        return self.connection_rooms.get(sid, set())

    async def broadcast_to_user(self, user_id: str, message: dict):
        """
        Broadcast a message to all connections in a user's room.

        Args:
            user_id: User ID to broadcast to
            message: Message dict to send
        """
        room = f"user_{user_id}"
        await self.broadcast("user_message", message, room=room)


# Global connection manager
manager = ConnectionManager()


# Functions compatible with the old API
async def broadcast_agent_update(agent_id: str, state: str, data: dict = None):
    """Broadcast an agent update."""
    message = {
        "type": "agent_update",
        "agent_id": agent_id,
        "state": state,
        "data": data or {},
    }
    await manager.broadcast("agent_update", message)


async def broadcast_task_update(task_id: str, state: str, data: dict = None):
    """Broadcast a task update."""
    message = {
        "type": "task_update",
        "task_id": task_id,
        "state": state,
        "data": data or {},
    }
    await manager.broadcast("task_update", message)


async def broadcast_metrics_update(metrics: dict):
    """Broadcast a metrics update."""
    message = {
        "type": "metrics_update",
        "metrics": metrics,
    }
    await manager.broadcast("metrics_update", message)


async def broadcast_log(level: str, message: str, source: str = None):
    """Broadcast a log message."""
    log_message = {
        "type": "log",
        "level": level,
        "message": message,
        "source": source,
    }
    await manager.broadcast("log", log_message)
