"""
WebSocket集成到FastAPI

提供WebSocket支持的FastAPI应用
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import json
import logging

logger = logging.getLogger(__name__)

# 连接管理器
class ConnectionManager:
    """简单的WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """广播消息给所有连接"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message: {e}")

    async def send_personal(self, message: dict, websocket: WebSocket):
        """发送消息给指定连接"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send personal message: {e}")


manager = ConnectionManager()


async def broadcast_agent_update(agent_id: str, state: str, data: dict = None):
    """广播Agent更新"""
    message = {
        "type": "agent_update",
        "agent_id": agent_id,
        "state": state,
        "data": data or {},
    }
    await manager.broadcast(message)


async def broadcast_task_update(task_id: str, state: str, data: dict = None):
    """广播任务更新"""
    message = {
        "type": "task_update",
        "task_id": task_id,
        "state": state,
        "data": data or {},
    }
    await manager.broadcast(message)


async def broadcast_metrics_update(metrics: dict):
    """广播指标更新"""
    message = {
        "type": "metrics_update",
        "metrics": metrics,
    }
    await manager.broadcast(message)


async def broadcast_log(level: str, message: str, source: str = None):
    """广播日志"""
    log_message = {
        "type": "log",
        "level": level,
        "message": message,
        "source": source,
    }
    await manager.broadcast(log_message)
