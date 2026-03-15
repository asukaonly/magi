"""
WebSocket real-time communication module.

Provides WebSocket server and connection management.
"""
from .server import WebSocketManager, create_socketio_app
from .events import (
    broadcast_agent_state,
    broadcast_task_state,
    broadcast_metrics,
    broadcast_log,
)

__all__ = [
    "WebSocketManager",
    "create_socketio_app",
    "broadcast_agent_state",
    "broadcast_task_state",
    "broadcast_metrics",
    "broadcast_log",
]
