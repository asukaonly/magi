"""
WebSocket集成到FastAPI

提供WebSocketsupport的FastAPI应用
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Dict, Set
import json
import logging

logger = logging.getLogger(__name__)


# connection管理器（support房间）
class ConnectionManager:
    """WebSocketconnection管理器（support房间）"""

    def __init__(self):
        # 活跃connection {sid: websocket}
        self.active_connections: Dict[str, WebSocket] = {}

        # 房间member {room: set of sids}
        self.rooms: Dict[str, Set[str]] = {}

        # connection所在房间 {sid: set of rooms}
        self.connection_rooms: Dict[str, Set[str]] = {}

    async def connect(self, sid: str, websocket: WebSocket):
        """接受WebSocketconnection"""
        await websocket.accept()
        self.active_connections[sid] = websocket
        self.connection_rooms[sid] = set()
        logger.info(f"WebSocket connected: {sid}. Total: {len(self.active_connections)}")

    def disconnect(self, sid: str):
        """disconnectWebSocketconnection"""
        if sid in self.active_connections:
            # 离开all房间
            if sid in self.connection_rooms:
                for room in list(self.connection_rooms[sid]):
                    self.leave_room(sid, room)

            del self.active_connections[sid]
            del self.connection_rooms[sid]
            logger.info(f"WebSocket disconnected: {sid}. Total: {len(self.active_connections)}")

    async def send_to_connection(self, sid: str, message: dict):
        """sendmessage到指定connection"""
        if sid in self.active_connections:
            try:
                await self.active_connections[sid].send_json(message)
            except Exception as e:
                logger.error(f"Failed to send to {sid}: {e}")
                self.disconnect(sid)

    async def broadcast(self, event: str, data: dict, room: str = None):
        """
        广播message

        Args:
            event: event名
            data: data
            room: 房间名（optional）
        """
        message = {
            "event": event,
            "data": data
        }

        if room:
            # send到房间内的allconnection
            if room in self.rooms:
                for sid in list(self.rooms[room]):
                    await self.send_to_connection(sid, message)
        else:
            # 广播到allconnection
            for sid in list(self.active_connections.keys()):
                await self.send_to_connection(sid, message)

    def join_room(self, sid: str, room: str):
        """加入房间"""
        if sid not in self.active_connections:
            return

        if room not in self.rooms:
            self.rooms[room] = set()

        self.rooms[room].add(sid)
        self.connection_rooms[sid].add(room)
        logger.info(f"Connection {sid} joined room {room}")

    def leave_room(self, sid: str, room: str):
        """离开房间"""
        if room in self.rooms:
            self.rooms[room].discard(sid)
            if not self.rooms[room]:
                del self.rooms[room]

        if sid in self.connection_rooms:
            self.connection_rooms[sid].discard(room)

        logger.info(f"Connection {sid} left room {room}")

    def get_client_count(self) -> int:
        """getconnection的clientquantity"""
        return len(self.active_connections)

    def get_clients_in_room(self, room: str) -> int:
        """get房间内的clientquantity"""
        return len(self.rooms.get(room, set()))

    def get_connection_rooms(self, sid: str) -> Set[str]:
        """getconnection所在的all房间"""
        return self.connection_rooms.get(sid, set())


# globalconnection管理器
manager = ConnectionManager()


# compatibleoldAPI的Function
async def broadcast_agent_update(agent_id: str, state: str, data: dict = None):
    """广播Agentupdate"""
    message = {
        "type": "agent_update",
        "agent_id": agent_id,
        "state": state,
        "data": data or {},
    }
    await manager.broadcast("agent_update", message)


async def broadcast_task_update(task_id: str, state: str, data: dict = None):
    """广播任务update"""
    message = {
        "type": "task_update",
        "task_id": task_id,
        "state": state,
        "data": data or {},
    }
    await manager.broadcast("task_update", message)


async def broadcast_metrics_update(metrics: dict):
    """广播metricupdate"""
    message = {
        "type": "metrics_update",
        "metrics": metrics,
    }
    await manager.broadcast("metrics_update", message)


async def broadcast_log(level: str, message: str, source: str = None):
    """广播Log"""
    log_message = {
        "type": "log",
        "level": level,
        "message": message,
        "source": source,
    }
    await manager.broadcast("log", log_message)
