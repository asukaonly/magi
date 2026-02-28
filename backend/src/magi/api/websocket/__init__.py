"""
WebSocket module for real-time communication.

Provides modular WebSocket handling with:
- Connection management (rooms, broadcasting)
- Message handler registry pattern
- Easy integration with FastAPI

Usage:
    from magi.api.websocket import register_websocket, manager

    app = FastAPI()
    register_websocket(app)

    # Broadcast to all clients
    await manager.broadcast("event_name", {"data": "value"})

    # Broadcast to a room
    await manager.broadcast("event_name", {"data": "value"}, room="user_123")

    # Broadcast to a user
    await manager.broadcast_to_user("user_123", {"data": "value"})
"""

from ..connection_manager import (
    ConnectionManager,
    broadcast_agent_update,
    broadcast_log,
    broadcast_metrics_update,
    broadcast_task_update,
    manager,
)
from .handlers import (
    MessageHandlerRegistry,
    WebSocketContext,
    handler_registry,
)
from .router import register_websocket, websocket_endpoint

__all__ = [
    # Connection management
    "ConnectionManager",
    "manager",
    # Broadcasting
    "broadcast_agent_update",
    "broadcast_task_update",
    "broadcast_metrics_update",
    "broadcast_log",
    # Handler registry
    "MessageHandlerRegistry",
    "WebSocketContext",
    "handler_registry",
    # Router
    "register_websocket",
    "websocket_endpoint",
]
